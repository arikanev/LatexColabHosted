# Latex-colab agent

from openai import OpenAI
import base64
import io
from set_api_keys import *
from pathlib import Path

from LLM_Models import models, name_hint
from textwrap import dedent

from PickLatexPrompts import LaTeXEnvTracker

import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging
import subprocess
import argparse

from Client_example import send_box, send_log, shutdown_server

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class Agent:

    def __init__(
            self, 
            latexfile: str | Path, 
            git_repo_path: str | Path=None, 
            conditioned_start=True,
            default_model="claude-3.7-sonnet:thinking"
    ):
        """
        Latex collaborator agent. Changes made in the local latex file are picked up by the agent. The agent itself is triggered
        by creating or modifying an exisiting user environment containing the keyword 'status=start', e.g.,:

        \\begin{user}
        How much is 1+1 ?
        %parameters: model=o1, status=start
        \\end{user}

        The agent will start streaming in a response environment upon saving the file locally or via synchronization with the remote overleaf.

        \\begin{answer}
        .....
        \\end{answer}
        
        \\begin{reasoning}
        .....
        \\end{reasoning}

        Changes made to latexfile are first copied to the git_repo_path and then pushed to remote for syncronizing with Overleaf.

        Args:
            latexfile (str | Path):      Path to local latex file.
            git_repo_path (str | Path):  Path to local git repository.
            conditioned_start (True):    Agent starts only when called via "status=start"
            default_model (str):         Default LLM
        """

        self.latexfile = latexfile
        self.git_repo_path = git_repo_path
        self.tracker = LaTeXEnvTracker(latexfile)
        self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=OPENROUTER_API_KEY,
                )
        self.last_modified = time.time()
        self.cooldown = 2
        self.streaming = False
        self.last_token = ''
        self.conditioned_start = conditioned_start

        self.default_model = name_hint(default_model)

        self.system = dedent("""\
            You are an advanced latex collaborator agent. Use latex formatting when writing down equations and
            manipulating symbolic math. Your output is embedded entirely within a latex environment and so you
            should not use triple quotation designation for the latex code and likewise you should avoid
            using begin{document} and end{document}.
        """)
        
        class Handler(FileSystemEventHandler):
            def on_modified(self_, event):
                if self.streaming:
                    return
                if (not event.is_directory and time.time() - self.last_modified > self.cooldown) \
                    or os.environ['LATEX_PULLED'] == 'True':
                    os.environ['LATEX_PULLED'] = 'False'
                    self.trigger()
            
            def on_created(self_, event):
                if not event.is_directory:
                    print(f"File created: {event.src_path}")
            
            def on_deleted(self_, event):
                if not event.is_directory:
                    print(f"File deleted: {event.src_path}")
            
            def on_moved(self_, event):
                print(f"File moved from {event.src_path} to {event.dest_path}")
        
        handler = Handler()
        self.observer = Observer()
        self.observer.schedule(handler, latexfile, recursive=True)
        self.observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()


    def git_push(self):

        if not self.git_repo_path:
            return
        
        os.environ['GIT_PUSH_DISABLED'] = 'True'
        
        # Copy the modified file to the git repository
        file_name = os.path.basename(self.latexfile)
        dest_path = os.path.join(self.git_repo_path, file_name)
    
        with open(self.latexfile, 'r', encoding='utf-8') as source_file:
            content = source_file.read()
        
        with open(dest_path, 'w', encoding='utf-8') as dest_file:
            dest_file.write(content)

        # Git operations - move to git repo directory first
        os.chdir(self.git_repo_path)
        original_dir = os.getcwd()
        
        # Add and commit the file
        try:
            subprocess.run(["git", "add", file_name], check=True)
            subprocess.run(["git", "commit", "-m", f"Auto-update: {file_name}"], check=True)
            
            # Push to Overleaf
            logger.info("Pushing changes to Overleaf...")
            send_log(message="Pushing changes to Overleaf...", level=0)
            result = subprocess.run(["git", "push", "origin", "master"], 
                                check=True, 
                                capture_output=True, 
                                text=True)
            
            logger.info("Successfully pushed changes to Overleaf!")
            send_log(message="Successfully pushed changes to Overleaf!", level=0)
        except subprocess.CalledProcessError as e:
            logger.error(f"Git operation failed: {e.stderr if hasattr(e, 'stderr') else str(e)}")
            send_log(message=f"Git operation failed: {e.stderr if hasattr(e, 'stderr') else str(e)}", level=0)
        finally:
            # Return to original directory
            os.chdir(original_dir)

        os.environ['GIT_PUSH_DISABLED'] = 'False'


    def think(self, query, params={}):
        model = params.get("model", self.default_model)
        logger.info(f"Calling model: {model}")
        send_box(content=f"{params}", title=f"Calling", level=1)
        self.completion = self.client.chat.completions.create(
                model=name_hint(model),
                messages=[
                    {"role": "system",
                     "content": self.system},
                    {
                    "role": "user",
                    "content": query,
                    }
                ],
                extra_body={
                        "include_reasoning": True,  # Include the parameter for downstream processing
                    },
                #reasoning_effort="high",
                stream=True
                )
        
        for token in self.completion:
            if hasattr(token.choices[0].delta, 'reasoning') and (the_token := token.choices[0].delta.reasoning):
                yield the_token
            if the_token := token.choices[0].delta.content:
                self.last_token = the_token 
                break

    def answer(self):
        if self.last_token:
            yield self.last_token
        for token in self.completion:
            if the_token := token.choices[0].delta.content:
                yield the_token    
            

    def trigger(self):
        logging.info("Tracking changes...")
        self.tracker.commit(self.latexfile)
        self.differences = self.tracker.marked_env("status", "start")
        self.differences.extend(self.tracker.diff())

        #if self.differences:
        #self.tracker.current_envs = self.tracker._parse_environments(self.tracker.current_content)
        #self.last_modified = time.time()
        #self.tracker.save(self.latexfile)

        def character_generator(query):
            text = f"{time.time()}: Answering {query}. this is being streamed now....."
            for t in text:
                time.sleep(0.1)
                yield t

        if self.differences:
            self.last_modified = time.time()
            env = self.differences[0]

            env_type = env.get("type", "")
            env_text = env.get("text", "")
            env_params = env.get("params", {})
            model = name_hint(env_params.get("model", "claude-3.7-sonnet:thinking"))

            status = (not self.conditioned_start) or env_params.get("status", False)

            if env_type == "user" and env_text and status in ["start"]:
                self.streaming = True
                os.environ['LATEX_COLAB_AGENT_STREAMING']='True'
                self.tracker.commit(self.latexfile)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                env_params["status"] = f'Reasoning_{timestamp}'
                updated_text = env_text + "\n%parameters: " + \
                    ', '.join([f"{key}={value}" for key,value in env_params.items()])
                self.tracker.update_env(env, updated_text)
                self.tracker.save(self.latexfile)
                
                self.git_push()

                self.tracker.commit(self.latexfile)
                self.tracker.stream(
                    new_env={
                        "before":{env_type: env_text},
                        "after": {"reasoning": self.think(query=env_text, params=env_params)},
                        "title": f"by {model}"
                    },
                    output_file=self.latexfile
                )

                self.tracker.commit(self.latexfile)
                self.tracker.stream(
                    new_env={
                        "before":{env_type: env_text},
                        "after": {"answer": self.answer()},
                        "title": f"by {model}"
                    },
                    output_file=self.latexfile
                )

                self.tracker.commit(self.latexfile)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                env_params["status"] = f'completed_{timestamp}'
                updated_text = env_text + "\n%parameters: " + \
                    ', '.join([f"{key}={value}" for key,value in env_params.items()])
                self.tracker.update_env(env, updated_text)
                self.tracker.save(self.latexfile)
                self.tracker.commit(self.latexfile)

                # Check if index.lock exists in the git repo and remove it
                index_lock = Path(self.git_repo_path / ".git/index.lock")
                if index_lock.exists():
                    logger.info("Git may have crushed. Removing index.lock.")
                    send_box("Git may have crushed. Removing index.lock.", title="Reviving git", level=1)
                    index_lock.unlink(missing_ok=True) 

                self.git_push()
                self.streaming = False
                os.environ['LATEX_COLAB_AGENT_STREAMING']='False'



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Latex Collaborator Agent  Ver 0.0.1 by Crypsis')
    parser.add_argument('file_path', help='Path to the LaTeX file to monitor')
    parser.add_argument('--repo-path', default='./overleaf_repo', help='Local path for the git repository')
    parser.add_argument('--model', default="claude-3.7-sonnet:thinking", help='Default language model.')
    
    args = parser.parse_args()

    # source = Path("~/PythonDev/LatexColab/latex_samples/git_test/main.tex").expanduser()
    # source = Path("~/PythonDev/LatexColab/latex_samples/colab_test/local/main.tex").expanduser()
    # git_repo = Path("~/PythonDev/LatexColab/latex_samples/colab_test/67c5d8972683f1ee5d2c2dc0/").expanduser()

    source = Path(args.file_path).expanduser()
    git_repo = Path(args.repo_path).expanduser()

    if not source.exists(): # or not git_repo.exists():
        print("Latex source could not be found.")
    else:
        print(f"Collaborator agent started.\nMonitoring local latex file: {source}\nLocal git repository: {git_repo}\n")
        print(f"Default model: {args.model}")
        Agent(latexfile=source, git_repo_path=git_repo, conditioned_start=True, default_model=args.model)


    



