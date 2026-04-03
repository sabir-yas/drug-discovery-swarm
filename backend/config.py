"""All tunable hyperparameters in one place."""

# Swarm config
NUM_EXPLORER_AGENTS = 10
NUM_CHEMIST_AGENTS = 8
NUM_SAFETY_AGENTS = 4
MOLECULES_PER_GENERATION = 200
MAX_GENERATIONS = 50

# Evolutionary config
ELITE_FRACTION = 0.1          # top 10% survive unchanged
MUTATION_RATE = 0.3
CROSSOVER_RATE = 0.5
TOURNAMENT_SIZE = 5

# Molecule constraints
MIN_HEAVY_ATOMS = 10
MAX_HEAVY_ATOMS = 50
MAX_MOLECULAR_WEIGHT = 500.0

# Scoring weights (for composite fitness)
BINDING_WEIGHT = 0.5
DRUG_LIKENESS_WEIGHT = 0.3
TOXICITY_PENALTY_WEIGHT = 0.2

# Server
WEBSOCKET_BROADCAST_INTERVAL = 0.5  # seconds
REDIS_URL = "redis://localhost:6379"
