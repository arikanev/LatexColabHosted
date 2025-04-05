# Basic FastAPI server structure
import uvicorn
from fastapi import FastAPI, HTTPException, Body
import tempfile
import shutil
import os
import subprocess
from urllib.parse import urlparse, urlunparse, quote
import logging
import re
from datetime import datetime
from textwrap import dedent
import time # Added missing import
from typing import Dict, Any, List # Added for type hinting
from fastapi.staticfiles import StaticFiles # Added
from fastapi.responses import FileResponse  # Added
from pydantic import BaseModel # Added for request body validation
from typing import Optional # Added for optional field
import redis # Added for locking
import hashlib # Added for lock key generation

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Redis Configuration (Added) ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379") # Default to local Redis if not set
# Create a Redis client instance
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping() # Test connection
    logger.info(f"Successfully connected to Redis at {REDIS_URL}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis at {REDIS_URL}: {e}")
    # Depending on requirements, you might exit or run without locking
    # For now, we'll log the error and continue, but locking will fail
    redis_client = None
except Exception as e:
    logger.error(f"An unexpected error occurred initializing Redis: {e}")
    redis_client = None

# Lock configuration (Added)
LOCK_TIMEOUT_MS = 30000 # 30 seconds expiration for the lock
LOCK_RETRY_DELAY_S = 0.5 # Delay between lock acquisition retries
LOCK_MAX_RETRIES = 5 # Maximum number of retries to acquire lock

app = FastAPI(
    title="LatexColab Server",
    description="API for interacting with Overleaf projects and processing LaTeX with AI.",
    version="0.1.0"
)

# --- Mount Static Files --- Added this section
# This will serve files from the 'static' directory relative to where the server.py is located.
# Make sure the 'static' directory exists in the same place as server.py (i.e., inside LatexColab)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- System Prompt for LLM ---
LLM_SYSTEM_PROMPT = dedent("""\
    You are an advanced latex collaborator agent. Use latex formatting when writing down equations and
    manipulating symbolic math. Your output is embedded entirely within a latex environment and so you
    should not use triple quotation designation for the latex code and likewise you should avoid
    using begin{document} and end{document}. Structure your response with a \\begin{reasoning}...\\end{reasoning} block followed by a \\begin{answer}...\\end{answer} block.
""")

DEFAULT_MODEL = "anthropic/claude-3.5-sonnet" # Default model if not specified

# --- Pydantic Models --- Updated

class ProcessPayload(BaseModel):
    latex_content: str

class LatexContent(BaseModel):
    latex_content: str

# --- Helper Functions (To be potentially moved to utils) ---

def _run_git_command(command: list[str], cwd: str):
    """Runs a Git command in a specified directory, capturing output and errors."""
    try:
        logger.info(f"Running git command: {' '.join(command)} in {cwd}")
        result = subprocess.run(
            command, 
            cwd=cwd, 
            check=True, 
            capture_output=True, 
            text=True,
            # Prevent git from prompting for credentials interactively
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'} 
        )
        logger.info(f"Git command successful: {result.stdout}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Git command failed: {' '.join(command)}")
        logger.error(f"Stderr: {e.stderr}")
        logger.error(f"Stdout: {e.stdout}")
        raise HTTPException(status_code=500, detail=f"Git operation failed: {e.stderr or e.stdout}")
    except Exception as e:
        logger.error(f"Unexpected error running git command: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during git operation: {str(e)}")

def _create_credential_url(git_url: str, token: str) -> str:
    """Injects URL-encoded credentials into a git URL."""
    try:
        if not token:
            # Raise HTTPException for bad request if token is missing
            raise HTTPException(status_code=400, detail="Overleaf token cannot be empty.")

        parsed_url = urlparse(git_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise HTTPException(status_code=400, detail="Invalid Git URL format provided.")

        # --- Extract clean hostname from netloc (strip potential user@ prefix) ---
        hostname_part = parsed_url.netloc
        if '@' in hostname_part:
            hostname_part = hostname_part.split('@', 1)[-1] # Get the part after the first @

        # URL-encode the token
        encoded_token = quote(token, safe='')

        # Construct netloc with username, *encoded* token, and *clean* hostname
        netloc = f"git:{encoded_token}@{hostname_part}"

        credential_url = urlunparse((
            parsed_url.scheme,
            netloc,
            parsed_url.path,
            parsed_url.params,
            parsed_url.query,
            parsed_url.fragment
        ))

        # Remove trailing '.git' if present (unlikely for Overleaf but safe)
        if credential_url.endswith('.git'):
            credential_url = credential_url[:-4]

        logger.info(f"Created credential URL for {parsed_url.netloc}")
        return credential_url
    except HTTPException as http_exc:
        # Re-raise specific HTTP exceptions
        raise http_exc
    except Exception as e:
        logger.error(f"Error creating credential URL: {str(e)}")
        # Generic error for unexpected issues during URL creation
        raise HTTPException(status_code=500, detail=f"Internal error creating credential URL: {str(e)}")

# --- LaTeX Parsing Helper Functions (Adapted from PickLatexPrompts.py) ---

def _parse_parameters_from_text(text: str) -> Dict[str, str]:
    """Parses parameters from a comment line like '%parameters: key=value, key2=value2'."""
    # --- Added Debug Logging --- 
    logger.info(f"Parsing parameters from text:\n{text}")
    # --- End Debug Logging --- 
    params = {}
    param_line = None
    # --- Replace regex search with line iteration for robustness ---
    lines = text.splitlines()
    for line in lines:
        stripped_line = line.strip()
        # logger.info(f"  Checking line: '{stripped_line}'") # Uncomment if needed
        if stripped_line.startswith('%parameters:'):
            param_line = stripped_line
            # --- Added Debug Logging --- 
            logger.info(f"  Found potential param line: '{param_line}'")
            # --- End Debug Logging --- 
            break # Found the line, stop searching

    if param_line:
        # Extract the part after '%parameters:'
        param_text = param_line.split('%parameters:', 1)[-1].strip()
        logger.info(f"  Extracted param text: '{param_text}'")
        # --- Key-value parsing: Split by comma first --- 
        params_list = param_text.split(',')
        logger.info(f"  Split param string into: {params_list}") # Log the split parts
        for item in params_list:
            item_stripped = item.strip()
            if '=' in item_stripped:
                # Split only on the first equals sign
                key_value = item_stripped.split('=', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    if key: # Ensure key is not empty
                        params[key] = value
                else:
                    logger.warning(f"  Could not parse key-value pair from: '{item_stripped}'")
            elif item_stripped: # Handle potential flag-like parameters without values?
                 logger.warning(f"  Found parameter without '=': '{item_stripped}'") # Or treat as flag?
    logger.info(f"  Finished parsing. Result params: {params}")
    return params

def _find_environments(content: str, env_name: str) -> List[Dict[str, Any]]:
    """Finds all occurrences of a specific LaTeX environment."""
    envs = []
    # Pattern to find \\begin{env_name} ... \\end{env_name} non-greedily
    pattern = re.compile(r'\\begin\{' + re.escape(env_name) + r'\}(.*?)\\end\{' + re.escape(env_name) + r'\}', re.DOTALL)
    for match in pattern.finditer(content):
        env_content = match.group(1)
        params = {}
        clean_text = env_content # Default clean text is the full content

        if env_name == 'user':
            params = _parse_parameters_from_text(env_content)
            # Remove the parameters line for the clean text
            clean_text = re.sub(r'^%\\s*parameters:.*?(?:\\n|$)', '', env_content, flags=re.MULTILINE).strip()

        envs.append({
            "type": env_name,
            "full_content": match.group(0), # The entire \\begin...\\end block
            "inner_content": env_content,    # Content between \\begin and \\end
            "clean_text": clean_text,        # Inner content without parameter line (for user)
            "params": params,
            "start": match.start(),
            "end": match.end()
        })
    return envs

# --- API Endpoints ---

@app.post("/fetch/")
def fetch_overleaf_file(
    git_url: str = Body(...),
    git_token: str = Body(...),
    relative_file_path: str = Body(...)
):
    """
    Clones an Overleaf repo and fetches the content of a specific file.
    - **git_url**: The HTTPS Git URL of the Overleaf project.
    - **git_token**: The Overleaf Git access token (or password).
    - **relative_file_path**: The path to the .tex file within the repository (e.g., 'main.tex').
    """
    temp_dir = None
    try:
        # 1. Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="latexcolab_fetch_")
        logger.info(f"Created temporary directory for fetch: {temp_dir}")

        # 2. Create URL with credentials
        credential_url = _create_credential_url(git_url, git_token)

        # 3. Clone the repository (shallow clone can be faster if repo is large)
        # Using depth 1 for potentially faster clone, might need full clone if history needed later
        _run_git_command(["git", "clone", "--depth", "1", credential_url, temp_dir], cwd=os.path.dirname(temp_dir))
        logger.info(f"Cloned repository {git_url} into {temp_dir}")

        # 4. Construct the target file path and check existence
        target_file = os.path.join(temp_dir, relative_file_path)
        if not os.path.isfile(target_file):
            logger.error(f"File not found in repository: {relative_file_path}")
            raise HTTPException(status_code=404, detail=f"File not found in repository: {relative_file_path}")

        # 5. Read the file content
        with open(target_file, 'r', encoding='utf-8') as f:
            file_content = f.read()
        logger.info(f"Successfully read file: {relative_file_path}")

        return {"relative_file_path": relative_file_path, "file_content": file_content}

    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly (like 404 or git errors)
        raise http_exc
    except Exception as e:
        logger.exception(f"An error occurred during fetch: {e}") # Log full traceback
        raise HTTPException(status_code=500, detail=f"An internal server error occurred during fetch: {str(e)}")
    finally:
        # 6. Clean up the temporary directory
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.error(f"Failed to clean up temporary directory {temp_dir}: {e}")

@app.post("/sync/")
def sync_overleaf(
    git_url: str = Body(...),
    git_token: str = Body(...),
    relative_file_path: str = Body(...),
    file_content: str = Body(...)
):
    """
    Clones an Overleaf repo, updates a file, and pushes the changes.
    - **git_url**: The HTTPS Git URL of the Overleaf project.
    - **git_token**: The Overleaf Git access token (or password).
    - **relative_file_path**: The path to the .tex file within the repository (e.g., 'main.tex').
    - **file_content**: The new content for the specified file.
    """
    logger.info(f"Received sync request for {relative_file_path} in repo {git_url}")

    if not redis_client:
        logger.warning("Redis client not available. Proceeding without locking.")
        # Decide if you want to allow proceeding without lock or raise an error
        # raise HTTPException(status_code=503, detail="Sync service temporarily unavailable due to Redis connection issue.")

    # --- Distributed Lock using Redis --- (Replaced TODO with implementation)
    # Create a unique lock key based on the git URL to ensure only one operation
    # per repository happens at a time.
    lock_key_base = f"lock:sync:{git_url}"
    # Use a hash to keep the key length manageable and avoid special chars
    lock_key = f"lock:sync:{hashlib.sha1(git_url.encode()).hexdigest()}"
    lock_acquired = False
    lock_value = f"lock_acquired_at_{time.time()}" # Unique value for the lock holder
    attempt = 0

    try:
        while attempt < LOCK_MAX_RETRIES and redis_client:
            lock_acquired = redis_client.set(lock_key, lock_value, nx=True, px=LOCK_TIMEOUT_MS)
            if lock_acquired:
                logger.info(f"Acquired lock {lock_key} for {git_url}")
                break
            else:
                attempt += 1
                logger.warning(f"Could not acquire lock {lock_key} for {git_url} (attempt {attempt}/{LOCK_MAX_RETRIES}). Retrying in {LOCK_RETRY_DELAY_S}s...")
                time.sleep(LOCK_RETRY_DELAY_S)

        if not lock_acquired:
            logger.error(f"Failed to acquire lock {lock_key} for {git_url} after {LOCK_MAX_RETRIES} attempts.")
            raise HTTPException(status_code=429, # Too Many Requests / Conflict
                                detail=f"Could not process sync for {git_url}. The repository is currently locked by another operation. Please try again shortly.")

        # --- Proceed with Git operations inside the lock ---
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"Created temporary directory: {tmpdir}")
            credential_url = _create_credential_url(git_url, git_token)

            try:
                # Clone the repo
                logger.info(f"Cloning {git_url} into {tmpdir}")
                _run_git_command(["git", "clone", credential_url, tmpdir], cwd=os.path.dirname(tmpdir))

                # Configure git user
                _run_git_command(["git", "config", "user.email", "agent@latexcolab.server"], cwd=tmpdir)
                _run_git_command(["git", "config", "user.name", "LatexColab Agent"], cwd=tmpdir)

                # Write the updated file content
                local_file_path = os.path.join(tmpdir, relative_file_path)
                # Ensure the directory exists in case the file is in a subfolder
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                logger.info(f"Writing content to {local_file_path}")
                with open(local_file_path, 'w', encoding='utf-8') as f:
                    f.write(file_content)

            except Exception as e:
                 logger.error(f"Error during git clone or file write for {git_url}: {e}")
                 # Raise specific HTTP errors if possible, otherwise generic 500
                 if isinstance(e, HTTPException):
                     raise e
                 else:
                     raise HTTPException(status_code=500, detail=f"Failed to prepare repository or write file: {str(e)}")

            # --- Git Commit and Push ---
            try:
                # Check git status
                status_output = _run_git_command(["git", "status", "--porcelain"], cwd=tmpdir)
                if not status_output or relative_file_path not in status_output:
                    logger.info("No changes detected in the file. Nothing to commit or push.")
                    # No need to raise error, just return success
                    # return {"message": "No changes detected. Sync successful (no action needed)."
                    # NOTE: We let it fall through to the final return for consistency
                else:
                    logger.info(f"Changes detected:\n{status_output}")
                    # Add, commit, and push
                    commit_message = f"Update {relative_file_path} via API sync - {datetime.now().isoformat()}" # Corrected var name
                    _run_git_command(["git", "add", local_file_path], cwd=tmpdir)
                    _run_git_command(["git", "commit", "-m", commit_message], cwd=tmpdir)

                    # --- Push with credential URL --- (Corrected push command)
                    logger.info(f"Pushing changes to {git_url} (master branch)...")
                    # Use the credential_url for push, not the original git_url
                    # Ensure correct branch name if not always master (e.g., main)
                    # TODO: Consider making branch configurable or detecting default
                    _run_git_command(["git", "push", "origin", "master"], cwd=tmpdir)
                    logger.info(f"Successfully synced and pushed changes for {relative_file_path}")

            except HTTPException as http_exc:
                # Handle specific git errors from _run_git_command
                error_detail = str(http_exc.detail).lower()
                # Note: index.lock errors should be prevented by Redis lock, but handle defensively
                if "index.lock" in error_detail:
                    logger.error(f"Git lock file detected for {git_url} despite Redis lock. This shouldn't happen.")
                    raise HTTPException(status_code=500, # Internal Server Error
                                        detail="Internal sync conflict. Please try again.")
                elif "failed to push some refs" in error_detail or "non-fast-forward" in error_detail:
                     logger.warning(f"Git push failed for {git_url} (likely conflict or stale). Client needs to pull.")
                     raise HTTPException(status_code=409, # Conflict
                                         detail="Push rejected. Remote repository has changes. Please fetch/pull changes locally first before processing and syncing again.")
                else:
                    # Re-raise other git command errors
                    logger.error(f"Git operation failed during commit/push: {error_detail}")
                    raise http_exc
            except Exception as e:
                logger.error(f"Unexpected error during git commit/push for {git_url}: {e}")
                raise HTTPException(status_code=500, detail=f"An unexpected error occurred during git sync: {str(e)}")

    finally:
        # --- Release the lock --- (Added)
        if lock_acquired and redis_client:
            # Use Lua script for safe deletion (only delete if value matches)
            # This prevents deleting a lock acquired by another process if this one timed out.
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                deleted = redis_client.eval(lua_script, 1, lock_key, lock_value)
                if deleted:
                    logger.info(f"Released lock {lock_key} for {git_url}")
                else:
                     # This could happen if the lock expired and another process acquired it
                     logger.warning(f"Did not release lock {lock_key} for {git_url} as value did not match (or key expired).")
            except Exception as e:
                logger.error(f"Failed to release lock {lock_key} for {git_url}: {e}")
                # This is serious, as the lock might remain stuck

    return {"message": f"Successfully synced changes for {relative_file_path}"}

@app.get("/", include_in_schema=False) # Exclude from OpenAPI docs
async def read_index():
    # Serve index.html from the static directory
    # Ensure index.html is inside the 'static' directory
    index_path = os.path.join("static", "index.html")
    if not os.path.exists(index_path):
         logger.error("static/index.html not found!")
         raise HTTPException(status_code=404, detail="Frontend not found. Is static/index.html present?")
    return FileResponse(index_path)

# Example of how to run this server (using uvicorn):
# Set OPENROUTER_API_KEY environment variable first!
# export OPENROUTER_API_KEY='your_key_here'
# uvicorn server:app --reload --app-dir LatexColab

if __name__ == "__main__":
    # Configuration for running directly (optional)
    # Use --host 0.0.0.0 to make it accessible on the network
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True) 