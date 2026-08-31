"""
Generates environment dicts to test a file against, from its list of
referenced env vars (see envscan.py). Not persisted to disk -- generated
fresh each run with a fixed seed, so results are reproducible without
growing the fixtures folder as more samples are added (decision made
2026-08-30, delegated by the user -- see chat).

<= threshold vars: full power-set (every on/off combination), since it's
   cheap and exhaustive at that size.
>  threshold vars: random sample (fixed seed for reproducibility), since
   the power-set explodes exponentially.

Always includes the fully-empty environment as a baseline, even in the
random-sample case, since "nothing set" is the single most common real
scenario and shouldn't be left to chance.
"""
import itertools
import random
from typing import Dict, List

POWER_SET_THRESHOLD = 6
RANDOM_SAMPLE_COUNT = 15  # user's choice
RANDOM_SEED = 42


def generate_environments(var_names: List[str]) -> List[Dict[str, str]]:
    n = len(var_names)
    if n == 0:
        return [{}]

    if n <= POWER_SET_THRESHOLD:
        envs = []
        for bits in itertools.product([False, True], repeat=n):
            env = {var_names[i]: "true" for i in range(n) if bits[i]}
            envs.append(env)
        return envs

    rng = random.Random(RANDOM_SEED)
    envs = [{}]
    for _ in range(RANDOM_SAMPLE_COUNT):
        env = {v: "true" for v in var_names if rng.random() < 0.5}
        envs.append(env)
    return envs
