# Obtaining Overleaf Git Access and Project ID

This guide will walk you through the process of obtaining the necessary credentials to use LatexColab with your Overleaf projects:

1. Overleaf API/Git Token
2. Project ID

## Prerequisites

- An Overleaf account (either free or premium)
- A project on Overleaf that you want to use with LatexColab

## Step 1: Enable Git Access in Overleaf

Overleaf provides Git access to your projects, which LatexColab uses for synchronization.

1. Log in to your Overleaf account at [overleaf.com](https://www.overleaf.com)
2. Go to your user settings by clicking on your name in the top-right corner and selecting "Account Settings"

   ![Account Settings](https://i.imgur.com/example1.png)

3. Navigate to the "Git" section in the left sidebar

   ![Git Section](https://i.imgur.com/example2.png)

4. If you haven't enabled Git access before, click on "Enable Git Access"

   - For Overleaf Premium users: Git access is included in your subscription
   - For free users: You may need to upgrade your account to get Git access

5. Once enabled, you'll see your Git credentials:
   - Your Git username will always be `git`
   - You'll be provided with a Git access token (this is your API token)

   ![Git Credentials](https://i.imgur.com/example3.png)

6. Copy your Git access token and keep it secure - you'll need it for LatexColab

## Step 2: Get Your Project's Git URL and Project ID

1. Navigate to the project you want to use with LatexColab
2. Click on the "Menu" button in the top-left corner
3. Select "Git" from the dropdown menu

   ![Project Git Access](https://i.imgur.com/example4.png)

4. You'll see a popup with your project's Git URL. It will look something like:
   ```
   https://git.overleaf.com/5f7b8d9a12c3e4001a123456
   ```

5. **Project ID**: The last part of the URL is your project ID. In the example above, the project ID is `5f7b8d9a12c3e4001a123456`

6. Copy the entire Git URL - you'll need both the URL and the Project ID for LatexColab

## Step 3: Configure LatexColab

Once you have both your Git access token and project information, you need to update the `lc` script with these details:

1. Open the `lc` script in a text editor
2. Find and update the following lines:

```bash
# Your Overleaf git URL
OVERLEAF_GIT_URL="https://git.overleaf.com/YOUR_PROJECT_ID"

# Your Overleaf login email (always 'git' for overleaf)
GIT_USERNAME="git"

# Your Overleaf API token (from Account Settings -> Git)
API_TOKEN="your_git_access_token_here"

# Local repository path
REPO_PATH="$HOME/path/to/where/you/want/the/repo/YOUR_PROJECT_ID"
```

3. Replace the placeholders with your actual information:
   - `YOUR_PROJECT_ID` in the `OVERLEAF_GIT_URL` with your project ID
   - `your_git_access_token_here` with the Git access token from Step 1
   - Adjust the `REPO_PATH` to your preferred local directory

## Security Notes

1. **Never share your Git access token** - it provides full access to all your Overleaf projects
2. Consider using environment variables instead of hardcoding tokens in scripts
3. If you believe your token has been compromised, you can regenerate it in Overleaf account settings

## Troubleshooting

### Authentication Failed

If you see "Authentication Failed" messages when LatexColab tries to connect to Overleaf:

1. Verify your Git access token is correct
2. Ensure you're using `git` as the username
3. Check if your Overleaf subscription is active (for premium features)

### Cannot Find Project

If LatexColab cannot find your project:

1. Verify the project ID in the Git URL
2. Make sure you have access to the project in Overleaf
3. For collaborative projects, ensure you have write access

### Token Expiration

Overleaf Git tokens may expire or be invalidated:

1. If synchronization stops working, generate a new token in Overleaf
2. Update the token in your LatexColab configuration

## Additional Resources

- [Overleaf Git Documentation](https://www.overleaf.com/learn/how-to/Using_Git_and_GitHub)
- [Overleaf API Documentation](https://www.overleaf.com/devs)