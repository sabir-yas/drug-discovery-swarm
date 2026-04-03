import sys

# Mock Redis globally so it doesn't fail on Windows where Redis isn't running
try:
    import fakeredis
    import redis
    redis.Redis = fakeredis.FakeRedis
except ImportError:
    print("Please install fakeredis: pip install fakeredis")

import asyncio
from coordinator import SwarmCoordinator

async def test_loop():
    print("Starting local test loop...")
    coordinator = SwarmCoordinator()
    
    # Run only 2 generations for a quick architecture test
    import config
    config.MAX_GENERATIONS = 2
    config.MOLECULES_PER_GENERATION = 10
    
    try:
        async for result in coordinator.run():
            if result["type"] == "generation_complete":
                print(f"Generation {result['generation']} Complete!")
                print(f" - Best Fitness: {result['best_fitness']:.4f}")
                print(f" - Total Checked: {result['total_explored']}")
                print(f" - Agents Reported: {len(result.get('agent_events', []))} events")
            elif result["type"] == "generation_update":
                print(f"  ... phase: {result['phase']}")
    except Exception as e:
        print(f"Pipeline error: {e}")

if __name__ == "__main__":
    asyncio.run(test_loop())
