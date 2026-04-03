#!/bin/bash
#SBATCH --account=amc-general
#SBATCH --time=02:00:00
#SBATCH --qos=normal
#SBATCH --partition=amilan
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --job-name=drug_discovery
#SBATCH --output=logs/%x.%j.out
#SBATCH --error=logs/%x.%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=yaseer.a.sabir@cuanschutz.edu

echo "===== JOB START ====="

# Ensure we run from the backend directory so uvicorn finds main.py
cd "$SLURM_SUBMIT_DIR"
echo "Working directory: $(pwd)"

echo "Nodes allocated:"
scontrol show hostnames $SLURM_JOB_NODELIST

module load anaconda/2023.09

# Don't let Python fall back to ~/.local site-packages — use only the conda env
export PYTHONNOUSERSITE=1

nodes=$(scontrol show hostnames $SLURM_JOB_NODELIST)
nodes_array=($nodes)

head_node=${nodes_array[0]}
echo "Head node: $head_node"

head_ip=$(srun --nodes=1 --ntasks=1 --mem=0 -w $head_node hostname)

port=6379
ip_head=$head_ip:$port
echo "Ray head address: $ip_head"

ray stop

# ==== REDIS ====
echo "Starting Redis server natively on head node..."
export REDIS_URL="redis://localhost:6379"
conda run -n drugswarm redis-server --daemonize yes
sleep 5

# ==== RAY HEAD ====
echo "Starting Ray head..."
srun --nodes=1 --ntasks=1 --mem=0 --overlap -w $head_node \
    conda run -n drugswarm ray start \
    --head \
    --node-ip-address=$head_ip \
    --port=$port \
    --num-cpus=$SLURM_CPUS_PER_TASK \
    --block &

sleep 20

# ==== RAY WORKERS ====
echo "Starting Ray workers..."
for node in "${nodes_array[@]:1}"; do
    echo "Worker node: $node"
    srun --nodes=1 --ntasks=1 --mem=0 --overlap -w $node \
        conda run -n drugswarm ray start \
        --address=$ip_head \
        --num-cpus=$SLURM_CPUS_PER_TASK \
        --block &
    sleep 10
done

# ==== WAIT FOR RAY TO BE READY ====
# Fixed sleeps aren't reliable — Ray GCS startup time varies.
# Poll until the cluster actually accepts connections before starting uvicorn.
echo "Polling Ray cluster at $ip_head until ready..."
RAY_READY=false
for attempt in $(seq 1 24); do
    if conda run -n drugswarm python -c \
        "import ray; ray.init(address='$ip_head', ignore_reinit_error=True); ray.shutdown()" \
        > /dev/null 2>&1; then
        echo "Ray is ready after attempt $attempt."
        RAY_READY=true
        break
    fi
    echo "  Not ready yet (attempt $attempt/24)... retrying in 5s"
    sleep 5
done

if [ "$RAY_READY" = false ]; then
    echo "ERROR: Ray cluster at $ip_head did not become ready within 2 minutes. Aborting."
    exit 1
fi

# ==== UVICORN ====
echo "Starting backend API server natively..."

# Pass the Ray address explicitly so coordinator.py doesn't need to guess
export RAY_ADDRESS="$ip_head"

# Note: all args must be on ONE continued line — a blank line breaks shell continuation
conda run -n drugswarm \
    uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    >> logs/uvicorn."$SLURM_JOB_ID".out \
    2>> logs/uvicorn."$SLURM_JOB_ID".err &

UVICORN_PID=$!
echo "Uvicorn PID: $UVICORN_PID"

sleep 10

# Crash guard
if ! kill -0 $UVICORN_PID 2>/dev/null; then
    echo "ERROR: Uvicorn exited immediately. Dumping error log:"
    cat logs/uvicorn."$SLURM_JOB_ID".err
    exit 1
fi
echo "Uvicorn is running on port 8000."

# ==== REVERSE SSH TUNNEL ====
# Alpine compute nodes block inbound TCP from the login node.
# The reverse tunnel has the compute node push port 8000 outbound to the login
# node (allowed), so Windows can forward-tunnel from there.
#
# ONE-TIME SETUP on login node (if not done already):
#   cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
#   chmod 600 ~/.ssh/authorized_keys
#
LOGIN_NODE="login.rc.colorado.edu"
echo "Opening reverse tunnel: ${LOGIN_NODE}:8000 <- localhost:8000"

ssh -f -N \
    -R 8000:localhost:8000 \
    -o StrictHostKeyChecking=no \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=5 \
    "$LOGIN_NODE"

TUNNEL_EXIT=$?
if [ $TUNNEL_EXIT -ne 0 ]; then
    echo "WARNING: Reverse tunnel failed (exit $TUNNEL_EXIT)."
    echo "Check: cat ~/.ssh/authorized_keys on the login node."
    echo "Fallback forward tunnel (may be firewall-blocked):"
    echo "  ssh -N -L 8080:${head_node}:8000 ysabir@xsede.org@${LOGIN_NODE}"
else
    echo "Reverse tunnel active."
    echo ""
    echo "=== CONNECT FROM WINDOWS ==="
    echo "  ssh -N -L 8080:localhost:8000 ysabir@xsede.org@${LOGIN_NODE}"
    echo "  Then open: http://localhost:8080"
    echo "  WebSocket:  ws://localhost:8080/ws"
    echo "============================"
fi

wait

echo "===== JOB FINISHED ====="
