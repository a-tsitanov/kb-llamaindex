#!/usr/bin/env bash
# Runs loader.py on srv02 in a throwaway kb-app:offline container on the kb network.
#   cd ~/loadtest && setsid nohup ./run-loader.sh set-s1.txt lt-s1 4 > loader-lt-s1.out 2>&1 < /dev/null &
set -eu
KEY=$(docker exec kb-webui-1 printenv KB_API_KEY)
docker run --rm --name "loader-$2" --network kb_default \
  -e KB_API_URL=http://api:8000 -e DOCS2MD_URL=http://10.10.113.11:8070 -e KB_API_KEY="$KEY" \
  -v "$HOME/loadtest:/lt" kb-app:offline \
  python /lt/loader.py --list "/lt/$1" --root /lt/all --tag "$2" --log "/lt/$2.jsonl" --workers "${3:-4}"
