#!/bin/bash
# heroku_config_setter.sh - Set Heroku config vars from .env file (WSL2 / Ubuntu version)

# Check if heroku CLI is installed
if ! command -v heroku &> /dev/null
then
    echo "❌ Error: heroku CLI not found. Install it with:"
    echo "curl https://cli-assets.heroku.com/install-ubuntu.sh | sh"
    exit 1
fi

# Usage help
if [ "$#" -ne 1 ]; then
    echo "Usage: ./scripts/heroku_config_setter.sh <your-app-name>"
    exit 1
fi

APP_NAME=$1
ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: $ENV_FILE not found."
    exit 1
fi

echo "Reading configurations from $ENV_FILE for app $APP_NAME..."

# Build the command string
# We filter out comments and empty lines, then join into a single heroku command for speed
CMD="heroku config:set"
COUNT=0

while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.* ]] && continue
    [[ -z "$line" ]] && continue
    
    # Simple check for KEY=VALUE
    if [[ "$line" == *"="* ]]; then
        CMD="$CMD $line"
        COUNT=$((COUNT+1))
    fi
done < "$ENV_FILE"

if [ $COUNT -eq 0 ]; then
    echo "No variables found to set."
    exit 0
fi

CMD="$CMD --app $APP_NAME"

echo "The following $COUNT variables will be set (values hidden):"
while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.* ]] && continue
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"="* ]]; then
        KEY=$(echo "$line" | cut -d'=' -f1)
        echo "  $KEY = (hidden)"
    fi
done < "$ENV_FILE"

read -p "Proceed? [y/N]: " confirm
if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
    eval $CMD
    echo "✅ Successfully set $COUNT variables."
else
    echo "Aborted."
fi
