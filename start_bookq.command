#!/bin/zsh
export PATH=/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH
cd "$(dirname "$0")"

# clear any old copy of the site that is still holding the port
pkill -f "streamlit run bookq.py" 2>/dev/null
lsof -ti :8501 | xargs kill -9 2>/dev/null
# stop the site again when this window is closed
trap 'pkill -f "streamlit run bookq.py" 2>/dev/null' EXIT HUP INT TERM

echo "1/3 Checking Docker..."
if ! docker info >/dev/null 2>&1; then
  open -a Docker
  echo "Waiting for Docker to start..."
  until docker info >/dev/null 2>&1; do sleep 2; done
fi

echo "2/3 Starting Oracle..."
docker start oracle-free >/dev/null 2>&1
for i in $(seq 1 60); do
  s=$(docker inspect -f '{{.State.Health.Status}}' oracle-free 2>/dev/null)
  echo "   Oracle status: $s"
  [ "$s" = "healthy" ] && break
  sleep 3
done

echo "3/3 Starting BookQ. Close this window to stop it."
(sleep 6; open "http://localhost:8501") &
.venv/bin/streamlit run bookq.py --server.headless true --server.port 8501
