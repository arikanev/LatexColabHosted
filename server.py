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
from openai import OpenAI # Added for LLM interaction
import time # Added missing import
from typing import Dict, Any, List # Added for type hinting
from fastapi.staticfiles import StaticFiles # Added
from fastapi.responses import FileResponse  # Added
from pydantic import BaseModel # Added for request body validation

# --- Environment Variable Check ---
# Ensure OpenRouter API key is set
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    # This provides a warning but allows the server to start. 
    # Calls to /process will fail if the key isn't set at runtime.
    print("WARNING: OPENROUTER_API_KEY environment variable not set. AI processing will fail.")
    # raise ValueError("OPENROUTER_API_KEY environment variable is not set.") # Alternatively, raise error at startup

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LatexColab Server",
    description="API for interacting with Overleaf projects and processing LaTeX with AI.",
    version="0.1.0"
)

# --- Mount Static Files --- Added this section
# This will serve files from the 'static' directory relative to where the server.py is located.
# Make sure the 'static' directory exists in the same place as server.py (i.e., inside LatexColab)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- OpenAI Client Initialization ---
# Initialize only if the key exists, otherwise methods using it will check
client = None
if OPENROUTER_API_KEY:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    logger.info("OpenRouter client initialized.")
else:
    logger.warning("OpenRouter client not initialized due to missing API key.")

# --- System Prompt for LLM ---
LLM_SYSTEM_PROMPT = dedent("""\
    You are an advanced latex collaborator agent. Use latex formatting when writing down equations and
    manipulating symbolic math. Your output is embedded entirely within a latex environment and so you
    should not use triple quotation designation for the latex code and likewise you should avoid
    using begin{document} and end{document}. Structure your response with a \\begin{reasoning}...\\end{reasoning} block followed by a \\begin{answer}...\\end{answer} block.
""")

DEFAULT_MODEL = "anthropic/claude-3.5-sonnet" # Default model if not specified

# --- Pydantic Models --- Added this section

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

# --- AI Processing Function ---

def _call_llm_for_prompt(prompt_text: str, params: Dict[str, str]) -> Dict[str, str]:
    """Calls the LLM via OpenRouter, expecting reasoning and answer."""
    global client # Access the globally initialized client
    if not client:
         raise HTTPException(status_code=500, detail="OpenRouter client not initialized. Is OPENROUTER_API_KEY set?")
         
    model = params.get("model", DEFAULT_MODEL).strip()
    # Basic model name cleaning (replace common separators if needed)
    model = model.replace(":", "/") # e.g., claude-3.5-sonnet:thinking -> anthropic/claude-3.5-sonnet
    # Add more cleaning/mapping if needed based on common user inputs

    logger.info(f"Calling LLM: {model} for prompt: '{prompt_text[:50]}...'")

    reasoning_content = ""
    answer_content = ""
    start_time = time.time()

    try:
        # Use stream=True to potentially get reasoning first if model supports it
        # Note: OpenRouter's `include_reasoning` is model-specific and might not work universally.
        # We will construct reasoning/answer blocks from the standard response structure.
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text}
            ],
            stream=False # Changed to False for simpler handling first, can revisit streaming
            # extra_body={ # This might not be standard or supported by all models via OpenRouter
            #     "include_reasoning": True, 
            # }
        )
        
        # Assume the full response is the answer for now
        # A more sophisticated approach might parse the response if the model
        # explicitly separates reasoning, but that's not guaranteed.
        # We rely on the system prompt asking for reasoning/answer blocks.
        full_response = completion.choices[0].message.content or ""
        
        # Basic split: Assume reasoning block comes first if present
        reasoning_match = re.search(r"\\\\begin\{reasoning\}(.*?)\\\\end\{reasoning\}", full_response, re.DOTALL)
        answer_match = re.search(r"\\\\begin\{answer\}(.*?)\\\\end\{answer\}", full_response, re.DOTALL)

        if reasoning_match and answer_match:
             reasoning_content = reasoning_match.group(1).strip()
             answer_content = answer_match.group(1).strip()
        elif answer_match: # Only answer found
             answer_content = answer_match.group(1).strip()
             reasoning_content = "[No reasoning block provided by model]"
        else: # Neither block found, put entire response in answer
             answer_content = full_response.strip()
             reasoning_content = "[Model did not provide standard reasoning/answer blocks]"


    except Exception as e:
        logger.error(f"Error calling LLM ({model}): {e}")
        # Return error messages within the blocks
        reasoning_content = f"[Error during LLM call: {str(e)}]"
        answer_content = f"[Error during LLM call: {str(e)}]"

    end_time = time.time()
    duration_seconds = int(end_time - start_time)
    duration_minutes = duration_seconds // 60
    duration_remaining_seconds = duration_seconds % 60
    
    # Add metadata to the answer block title
    answer_title = f"by {model} (generated in {duration_minutes} minutes and {duration_remaining_seconds} seconds.)"

    logger.info(f"LLM call finished in {duration_seconds}s. Answer length: {len(answer_content)}")

    return {
        "reasoning": reasoning_content,
        "answer": answer_content,
        "answer_title": answer_title
    }

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

        return {"message": "Fetch successful", "file_content": file_content}

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
    temp_dir = None
    try:
        # 1. Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="latexcolab_sync_")
        logger.info(f"Created temporary directory: {temp_dir}")

        # 2. Create URL with credentials
        credential_url = _create_credential_url(git_url, git_token)

        # 3. Clone the repository
        _run_git_command(["git", "clone", credential_url, temp_dir], cwd=os.path.dirname(temp_dir))
        logger.info(f"Cloned repository {git_url} into {temp_dir}")
        
        # Configure git user for commit inside the repo
        # Use a generic identity as the specific user is authenticated via token
        _run_git_command(["git", "config", "user.email", "agent@latexcolab.server"], cwd=temp_dir)
        _run_git_command(["git", "config", "user.name", "LatexColab Agent"], cwd=temp_dir)

        # 4. Write the updated file content
        target_file = os.path.join(temp_dir, relative_file_path)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(file_content)
        logger.info(f"Updated file: {target_file}")

        # 5. Git Add, Commit, Push
        _run_git_command(["git", "add", relative_file_path], cwd=temp_dir)
        # Check if there are changes to commit
        status_result = subprocess.run(["git", "status", "--porcelain"], cwd=temp_dir, capture_output=True, text=True)
        if relative_file_path in status_result.stdout:
             _run_git_command(["git", "commit", "-m", f"Auto-update: {relative_file_path} via API"], cwd=temp_dir)
             _run_git_command(["git", "push", "origin", "master"], cwd=temp_dir)
             logger.info(f"Committed and pushed changes for {relative_file_path}")
        else:
             logger.info("No changes detected in the file to commit.")

        # Return the absolute path of the temp dir for debugging, maybe remove later
        # Note: Returning file paths from APIs can be a security risk if not handled carefully on the client.
        # Consider returning only success/failure messages in production.
        return {"message": "Sync successful", "processed_in_dir": os.path.abspath(temp_dir)} 

    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly
        raise http_exc
    except Exception as e:
        logger.exception(f"An error occurred during sync: {e}") # Log full traceback
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")
    finally:
        # 6. Clean up the temporary directory
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.error(f"Failed to clean up temporary directory {temp_dir}: {e}")

@app.post("/process/")
def process_latex_with_ai(payload: LatexContent):
    """
    Finds the first '\\begin{user}' block with 'status=start', 
    calls the LLM, inserts the response, updates the status, and returns the modified content.
    - **payload**: JSON body containing {"latex_content": "..."}
    """
    # --- Access content via payload object ---
    latex_content = payload.latex_content
    
    # --- Corrected Debug Logging (Show start of ACTUAL received content) ---
    log_preview_length = 2000 # Log more characters to be sure
    logged_content_preview = latex_content[:log_preview_length]
    if len(latex_content) > log_preview_length:
        logged_content_preview += "... [truncated in log]"
    logger.info(f"Received latex_content preview:\n{logged_content_preview}")
    # --- End Debug Logging ---

    if not client:
        raise HTTPException(status_code=500, detail="AI Processing Error: OpenRouter client not initialized. API key missing?")

    user_envs = _find_environments(latex_content, 'user')
    # --- Added Debug Logging --- 
    logger.info(f"Found {len(user_envs)} user environments. Checking parameters...")
    for i, env in enumerate(user_envs):
        logger.info(f"  Env {i} Params: {env['params']} | Status param value: '{env['params'].get('status')}'")
    # --- End Debug Logging ---
    
    target_env = None
    for env in user_envs:
        if env['params'].get('status', '').strip().lower() == 'start':
            target_env = env
            break # Process only the first one found

    if not target_env:
        logger.info("No user prompts with 'status=start' found for processing.")
        # Return original content if no prompt needs processing
        return {"message": "No prompts found to process", "processed_content": latex_content, "processed": False}

    logger.info(f"Processing user prompt starting at index {target_env['start']}")
    
    # Call the LLM
    try:
        llm_response = _call_llm_for_prompt(target_env['clean_text'], target_env['params'])
    except HTTPException as http_exc: # Catch specific LLM call errors
         raise http_exc
    except Exception as e:
         logger.exception("Error during LLM processing logic")
         raise HTTPException(status_code=500, detail=f"Internal error during AI processing: {str(e)}")

    # --- Construct the new LaTeX string ---
    
    # Create timestamp for completed status
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    new_status = f"completed_{timestamp}"
    
    # Update the parameters line within the original user block content
    original_user_inner = target_env['inner_content']
    # Replace or add the status parameter
    if '%parameters:' in original_user_inner:
         updated_user_inner = re.sub(
             r'(%\\s*parameters:.*?)(status\\s*=\\s*start)(.*)', 
             r'\1status=' + new_status + r'\3', 
             original_user_inner, 
             flags=re.IGNORECASE | re.DOTALL
         )
         # If status=start wasn't found but %parameters: was, append it (edge case)
         if 'status=' + new_status not in updated_user_inner:
              updated_user_inner = re.sub(
                   r'(%\\s*parameters:.*?)$', 
                   r'\1, status=' + new_status, 
                   updated_user_inner, 
                   flags=re.MULTILINE | re.IGNORECASE
              )
    else: 
         # Add the parameters line if it didn't exist
         updated_user_inner = original_user_inner.strip() + f'\n%parameters: status={new_status}\n'
         
    updated_user_block = f'\\begin{{user}}{updated_user_inner}\\end{{user}}'

    # Format the reasoning and answer blocks
    reasoning_block = f'\\begin{{reasoning}}\n{llm_response["reasoning"]}\n\\end{{reasoning}}'
    answer_block = f'\\begin{{answer}}[{llm_response["answer_title"]}]\n{llm_response["answer"]}\n\\end{{answer}}'
    
    # Combine the new blocks
    new_blocks = f'\n{reasoning_block}\n\n{answer_block}\n'
    
    # --- Replace the original user block and insert new blocks ---
    # We replace the original user block with the updated one + the new blocks
    start_index = target_env['start']
    end_index = target_env['end']
    
    # Ensure indices are valid
    if start_index < 0 or end_index > len(latex_content) or start_index >= end_index:
         logger.error(f"Invalid indices found for replacement: start={start_index}, end={end_index}")
         raise HTTPException(status_code=500, detail="Internal error: Could not determine replacement location in LaTeX content.")
         
    modified_content = latex_content[:start_index] + updated_user_block + new_blocks + latex_content[end_index:]

    logger.info(f"Successfully processed prompt and updated content.")
    
    return {"message": "Prompt processed successfully", "processed_content": modified_content, "processed": True}

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
    # Ensure API key is set if running this way too
    if not OPENROUTER_API_KEY:
         print("ERROR: OPENROUTER_API_KEY must be set as an environment variable to run.")
    else:
         uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True) # Removed app_dir as uvicorn runs from workspace root by default now? Let's simplify. If issues, add app_dir="LatexColab" back. 