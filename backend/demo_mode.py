"""
Fallback local script to run the swarm pipeline entirely locally without distributed Ray nodes.
"""
import asyncio
from coordinator import SwarmCoordinator

async def demo_loop():
    print("Starting local demo loop...")
    coordinator = SwarmCoordinator()
    try:
        async for result in coordinator.run():
            
            if result["type"] == "generation_complete":
                print(f"Generation {result['generation']} Complete!")
                print(f" - Best Fitness: {result['best_fitness']:.4f}")
                print(f" - Validated Selected: {result['num_selected']}")
            elif result["type"] == "generation_update":
                print(f"... phase: {result['phase']}")
    except KeyboardInterrupt:
        print("\nPipeline interrupted safely.")

if __name__ == "__main__":
    asyncio.run(demo_loop())
