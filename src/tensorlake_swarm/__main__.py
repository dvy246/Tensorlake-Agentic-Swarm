"""Entry point: python -m tensorlake_swarm"""

import asyncio

from tensorlake_swarm.orchestrator import main

asyncio.run(main())
