import requests
import os
import re
import argparse
import logging
from datetime import datetime
from textwrap import dedent
from openai import OpenAI
import time
from typing import Dict, Any, List, Optional

# --- Constants (Adapted from server) ---
LLM_SYSTEM_PROMPT = dedent("""
    You are an advanced latex collaborator agent. Use latex formatting when writing down equations and
    manipulating symbolic math. Your output is embedded entirely within a latex environment and so you
    should not use triple quotation designation for the latex code and likewise you should avoid
    using begin{document} and end{document}. Structure your response with a \\\\begin{reasoning}...\\\\end{reasoning} block followed by a \\\\begin{answer}...\\\\end{answer} block.
""")

DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions (Adapted from original server.py logic) ---

def _parse_parameters_from_text(text: str) -> Dict[str, str]:
    """Parses parameters from a comment line like '%parameters: key=value, key2=value2'."""
    logger.debug(f"Parsing parameters from text:\n{text}")
    params = {}
    param_line = None
    lines = text.splitlines()
    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith('%parameters:'):
            param_line = stripped_line
            logger.debug(f"  Found potential param line: '{param_line}'")
            break

    if param_line:
        param_text = param_line.split('%parameters:', 1)[-1].strip()
        logger.debug(f"  Extracted param text: '{param_text}'")
        params_list = param_text.split(',')
        logger.debug(f"  Split param string into: {params_list}")
        for item in params_list:
            item_stripped = item.strip()
            if '=' in item_stripped:
                key_value = item_stripped.split('=', 1)
                if len(key_value) == 2:
                    key = key_value[0].strip()
                    value = key_value[1].strip()
                    if key:
                        params[key] = value
                else:
                    logger.warning(f"  Could not parse key-value pair from: '{item_stripped}'")
            elif item_stripped:
                 logger.warning(f"  Found parameter without '=': '{item_stripped}'")
    logger.debug(f"  Finished parsing. Result params: {params}")
    return params

def _find_environments(content: str, env_name: str) -> List[Dict[str, Any]]:
    """Finds all occurrences of a specific LaTeX environment."""
    logger.debug(f"Inside _find_environments for '{env_name}'. Searching {len(content)} characters.")
    # Log snippet again just before regex
    snippet = content[:200] + "... " + content[-200:] if len(content) > 400 else content # Shorter snippet
    logger.debug(f"_find_environments content snippet:\n{snippet}")

    # --- Test with Python 'in' operator --- (Added)
    literal_begin = r'\begin{user}'
    if literal_begin in content:
        logger.debug(f"Basic string search ('in') FOUND the literal string '{literal_begin}'")
    else:
        logger.debug(f"Basic string search ('in') did NOT find the literal string '{literal_begin}'")
    # --- End 'in' operator test ---

    # --- Test with simpler regex ---
    simple_pattern_str = r'\\begin\\{' + re.escape(env_name) + r'\\}'
    simple_match = re.search(simple_pattern_str, content)
    if simple_match:
        logger.debug(f"Simple pattern '{simple_pattern_str}' FOUND a match at index {simple_match.start()}")
    else:
        logger.debug(f"Simple pattern '{simple_pattern_str}' did NOT find any match.")
    # --- End simple regex test ---

    envs = []
    # Original pattern
    pattern_str = r'\\begin\{' + re.escape(env_name) + r'\}(.*?)\\end\{' + re.escape(env_name) + r'\}'
    logger.debug(f"Using complex pattern: {pattern_str} with re.DOTALL")
    pattern = re.compile(pattern_str, re.DOTALL)

    match_count = 0
    for match in pattern.finditer(content):
        match_count += 1
        logger.debug(f"  Complex pattern found match {match_count} from {match.start()} to {match.end()}")
        env_content = match.group(1)
        params = {}
        clean_text = env_content

        if env_name == 'user':
            params = _parse_parameters_from_text(env_content)
            clean_text = re.sub(r'^%\\\\s*parameters:.*?(?:\\\\n|$)', '', env_content, flags=re.MULTILINE).strip()

        envs.append({
            "type": env_name,
            "full_content": match.group(0),
            "inner_content": env_content,
            "clean_text": clean_text,
            "params": params,
            "start": match.start(),
            "end": match.end()
        })
    return envs

def _call_llm_for_prompt(prompt_text: str, params: Dict[str, str], api_key: str) -> Dict[str, str]:
    """Calls the LLM via OpenRouter using the provided API key."""
    try:
        local_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    except Exception as e:
         logger.error(f"Failed to initialize OpenRouter client: {e}")
         # In a client script, we might want to raise the exception or exit
         raise RuntimeError(f"Failed to initialize OpenRouter client: {e}")

    model = params.get("model", DEFAULT_MODEL).strip()
    model = model.replace(":", "/") # Normalize model name if needed

    logger.info(f"Calling LLM: {model} for prompt: '{prompt_text[:50]}...'")

    reasoning_content = ""
    answer_content = ""
    start_time = time.time()

    try:
        completion = local_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text}
            ],
            stream=False,
            max_tokens=params.get("max_tokens", 4000) # Allow overriding max_tokens via params
        )

        full_response = "[Error: Received invalid response structure from LLM API]"
        if completion and completion.choices and len(completion.choices) > 0:
            first_choice = completion.choices[0]
            if first_choice.message:
                full_response = first_choice.message.content or "[Error: LLM response content was empty]"
            else:
                 full_response = "[Error: LLM response did not contain expected message structure]"
                 logger.warning(f"LLM response missing message structure: {first_choice}")
        else:
             full_response = "[Error: LLM response did not contain expected choices list]"
             logger.warning(f"LLM response missing choices: {completion}")

        reasoning_match = re.search(r"\\begin{reasoning}(.*?)\\end{reasoning}", full_response, re.DOTALL)
        answer_match = re.search(r"\\begin{answer}(.*?)\\end{answer}", full_response, re.DOTALL)

        if reasoning_match and answer_match:
             reasoning_content = reasoning_match.group(1).strip()
             answer_content = answer_match.group(1).strip()
        elif answer_match:
             answer_content = answer_match.group(1).strip()
             reasoning_content = "[No reasoning block provided by model]"
        else:
             answer_content = full_response.strip()
             reasoning_content = "[Model did not provide standard reasoning/answer blocks]"

    except Exception as e:
        logger.error(f"Error calling LLM API ({model}): {e}")
        # Re-raise for the main script to handle
        raise RuntimeError(f"Error during LLM API call: {str(e)}")

    end_time = time.time()
    duration_seconds = int(end_time - start_time)
    duration_minutes = duration_seconds // 60
    duration_remaining_seconds = duration_seconds % 60

    answer_title = f"by {model} (generated in {duration_minutes} minutes and {duration_remaining_seconds} seconds.)"

    logger.info(f"LLM call finished in {duration_seconds}s. Answer length: {len(answer_content)}")

    return {
        "reasoning": reasoning_content,
        "answer": answer_content,
        "answer_title": answer_title
    }

# --- Main Processing Logic ---

def process_local_latex(
    local_file_path: str,
    openrouter_api_key: str,
    server_url: str,
    overleaf_git_url: str,
    overleaf_git_token: str,
    relative_file_path: str
):
    """
    Reads a local LaTeX file, finds the first 'user' prompt with 'status=start',
    calls the LLM, updates the file content locally, and then sends the full
    updated content to the server's /sync endpoint.
    """
    logger.info(f"Starting local processing for: {local_file_path}")

    # --- Read Local File ---
    try:
        with open(local_file_path, 'r', encoding='utf-8') as f:
            latex_content = f.read()
        logger.info(f"Successfully read {len(latex_content)} characters from {local_file_path}")
    except FileNotFoundError:
        logger.error(f"Error: Local file not found at {local_file_path}")
        return False
    except Exception as e:
        logger.error(f"Error reading local file {local_file_path}: {e}")
        return False

    # --- Log snippet of content before finding environments (Added Debug) ---
    content_snippet_length = 500 # Log first/last 500 chars
    log_content_preview = latex_content[:content_snippet_length]
    if len(latex_content) > content_snippet_length * 2:
        log_content_preview += f"\n... [content truncated ({len(latex_content)} chars total)] ...\n"
        log_content_preview += latex_content[-content_snippet_length:]
    elif len(latex_content) > content_snippet_length:
        log_content_preview += f"\n... [content truncated ({len(latex_content)} chars total)] ...\n"

    logger.debug(f"Content snippet being searched:\n--BEGIN SNIPPET--\n{log_content_preview}\n--END SNIPPET--")
    # --- End Log Snippet ---

    # --- Find Prompt ---
    user_envs = _find_environments(latex_content, 'user')
    target_env = None
    logger.info(f"Found {len(user_envs)} user environments. Checking parameters...")
    for i, env in enumerate(user_envs):
        logger.info(f"  Env {i} Params: {env['params']}")
        if env['params'].get('status', '').strip().lower() == 'start':
            target_env = env
            logger.info(f"Found user prompt with status=start at index {target_env['start']}")
            break

    if not target_env:
        logger.info("No user prompts with 'status=start' found. Nothing to process.")
        return True # Not an error, just nothing to do

    # --- Call LLM ---
    try:
        llm_response = _call_llm_for_prompt(target_env['clean_text'], target_env['params'], openrouter_api_key)
    except Exception as e:
        logger.error(f"Failed to get response from LLM: {e}")
        return False # Abort if LLM call fails

    # --- Construct Updated Content ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    new_status = f"completed_{timestamp}"
    original_user_inner = target_env['inner_content']

    # Update status in parameters line
    if '%parameters:' in original_user_inner:
         # Try to replace existing status=start
         updated_user_inner, n_subs = re.subn(
             r'(status\\s*=\\s*start)',
             r'status=' + new_status,
             original_user_inner,
             flags=re.IGNORECASE
         )
         # If status=start wasn't found, append the new status to the %parameters line
         if n_subs == 0:
              # First re.sub call
              updated_user_inner = re.sub(
                   r'(%parameters:.*?)$(?<!,)', 
                   r'\1, status=' + new_status,
                   updated_user_inner,
                   flags=re.MULTILINE | re.IGNORECASE
              )
              # Handle case where parameters line ends with comma (Corrected Indentation)
              updated_user_inner = re.sub(
                   r'(%parameters:.*?,)\s*$',
                   r'\1 status=' + new_status,
                   updated_user_inner,
                   flags=re.MULTILINE | re.IGNORECASE
              )
    else:
         # Add the parameters line if it didn't exist
         updated_user_inner = original_user_inner.strip() + f'\n%parameters: status={new_status}\n'

    updated_user_block = f'\\\\begin{{user}}{updated_user_inner}\\\\end{{user}}'
    reasoning_block = f'\\\\begin{{reasoning}}\\n{llm_response["reasoning"]}\\n\\\\end{{reasoning}}'
    answer_block = f'\\\\begin{{answer}}[{llm_response["answer_title"]}]\\n{llm_response["answer"]}\\n\\\\end{{answer}}'
    new_blocks = f'\n{reasoning_block}\n\n{answer_block}\n'

    # Replace original user block with updated user block + new reasoning/answer blocks
    start_index = target_env['start']
    end_index = target_env['end']
    if start_index < 0 or end_index > len(latex_content) or start_index >= end_index:
         logger.error(f"Invalid indices found for replacement: start={start_index}, end={end_index}")
         return False

    modified_content = latex_content[:start_index] + updated_user_block + new_blocks + latex_content[end_index:]
    logger.info(f"Successfully generated updated LaTeX content (new length: {len(modified_content)} chars).")

    # --- Write Updated Content Back to Local File ---
    try:
        with open(local_file_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        logger.info(f"Successfully updated local file: {local_file_path}")
    except Exception as e:
        logger.error(f"Error writing updated content to local file {local_file_path}: {e}")
        return False

    # --- Call Server /sync Endpoint ---
    sync_url = f"{server_url.rstrip('/')}/sync"
    payload = {
        "git_url": overleaf_git_url,
        "git_token": overleaf_git_token,
        "relative_file_path": relative_file_path,
        "file_content": modified_content # Send the full updated content
    }
    logger.info(f"Sending updated content to server sync endpoint: {sync_url} for file {relative_file_path}")

    try:
        response = requests.post(sync_url, json=payload)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        logger.info(f"Server sync successful: {response.json().get('message', 'OK')}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling server sync endpoint {sync_url}: {e}")
        # If the request failed, attempt to log the response content if available
        if e.response is not None:
            try:
                error_detail = e.response.json().get('detail', e.response.text)
                logger.error(f"Server response ({e.response.status_code}): {error_detail}")
            except json.JSONDecodeError:
                logger.error(f"Server response ({e.response.status_code}) was not valid JSON: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during server sync: {e}")
        return False


# --- Command Line Interface ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Locally process a LaTeX file using an LLM and sync with Overleaf via a server.")

    parser.add_argument("local_file", help="Path to the local .tex file to process.")
    parser.add_argument("--key", required=True, help="Your OpenRouter API Key.")
    parser.add_argument("--server", required=True, help="URL of the LatexColab server (e.g., http://localhost:8000 or your Render URL).")
    parser.add_argument("--git-url", required=True, help="Overleaf Git URL (e.g., https://git.overleaf.com/your_project_id).")
    parser.add_argument("--git-token", required=True, help="Overleaf Git access token.")
    parser.add_argument("--relative-path", required=True, help="Relative path of the file within the Overleaf project (e.g., main.tex or sections/intro.tex).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging.")


    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
             handler.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled.")


    # --- Execute Processing ---
    success = process_local_latex(
        local_file_path=args.local_file,
        openrouter_api_key=args.key,
        server_url=args.server,
        overleaf_git_url=args.git_url,
        overleaf_git_token=args.git_token,
        relative_file_path=args.relative_path
    )

    if success:
        logger.info("Processing and synchronization completed successfully.")
        exit(0)
    else:
        logger.error("Processing and synchronization failed.")
        exit(1) 