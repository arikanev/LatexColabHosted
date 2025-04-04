# Openrouter/replicate models

models = [
    "google/gemini-2.0-flash-thinking-exp:free",
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "x-ai/grok-2-vision-1212",
    "minimax/minimax-01",
    "openai/gpt-4o-2024-11-20",
    "openai/chatgpt-4o-latest",
    "openai/gpt-4-turbo",
    "meta-llama/llama-3.2-90b-vision-instruct",
    "meta-llama/llama-3.2-11b-vision-instruct",
    "nousresearch/hermes-2-pro-llama-3-8b",
    "mistralai/pixtral-12b",
    "mistralai/pixtral-large-2411",
    "qwen/qvq-72b-preview",
    "qwen/qwen-2-vl-72b-instruct",    #video
    "qwen/qwen-2-vl-7b-instruct",     #video
    "anthropic/claude-3.5-sonnet:beta",
    "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.7-sonnet:thinking",
    #"anthropic/claude-3.5-sonnet",
    #"openai/o1-mini-2024-09-12",
    #"openai/o1-preview",
    "openai/o1",
    "openai/o3-mini",
    "openai/o3-mini-high",
    "cohere/command-r-08-2024",
    "meta-llama/llama-3.3-70b-instruct",
    "perplexity/llama-3.1-sonar-large-128k-online",
    "perplexity/sonar-reasoning",
    "mistralai/mistral-large-2411",
    "meta-llama/llama-3.1-70b-instruct",
    "deepseek/deepseek-r1",
    #"deepseek/deepseek-r1:nitro",
    #"deepseek/deepseek-r1-distill-qwen-32b",
    #"deepseek/deepseek-r1-distill-llama-70b",
    #"deepseek/deepseek-chat",
    "mistralai/codestral-2501",
    "microsoft/phi-4",
    #"deepseek/deepseek-chat"
]

name_hint = lambda name: [m for m in models if name in m.lower()][0]

