"""
FastAPI server with WebSocket for real-time streaming to frontend.
Run: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
from pathlib import Path
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from coordinator import SwarmCoordinator
from a2a_router import router as a2a_router

app = FastAPI(title="Drug Discovery Swarm")

# Mount A2A router
app.include_router(a2a_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

coordinator = None
connected_clients: List[WebSocket] = []


async def broadcast(data: dict):
    """Send data to all connected frontend clients."""
    message = json.dumps(data)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


@app.on_event("startup")
async def startup_event():
    global coordinator
    coordinator = SwarmCoordinator()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            # Listen for commands from frontend (start, pause, config changes)
            data = await websocket.receive_text()
            command = json.loads(data)
            if command.get("action") == "start":
                asyncio.create_task(run_swarm())
            elif command.get("action") == "pause":
                coordinator.pause()
            elif command.get("action") == "resume":
                coordinator.resume()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def run_swarm():
    """Main swarm loop — runs generations and broadcasts results."""
    global coordinator
    async for generation_result in coordinator.run():
        await broadcast(generation_result)


@app.get("/api/status")
async def get_status():
    return coordinator.get_status()


@app.get("/api/molecule/{mol_id}")
async def get_molecule_3d(mol_id: str):
    """Return 3D conformer data. Runs in a thread so it doesn't block the event loop."""
    import asyncio
    return await asyncio.to_thread(coordinator.get_molecule_3d, mol_id)


@app.get("/api/leaderboard")
async def get_leaderboard():
    return coordinator.get_leaderboard()


@app.get("/api/leaderboard/export")
async def export_leaderboard():
    """Save leaderboard to leaderboard.json for offline Vina validation."""
    import json as _json
    lb = coordinator.get_leaderboard()
    path = "leaderboard.json"
    with open(path, "w") as f:
        _json.dump(lb, f, indent=2)
    return {"saved": path, "count": len(lb)}

@app.get("/.well-known/agent.json")
async def agent_card():
    """Serve the A2A agent card for Prompt Opinion discovery."""
    card_path = Path(__file__).parent / "a2a" / "agent_card.json"
    return JSONResponse(content=json.loads(card_path.read_text()))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
