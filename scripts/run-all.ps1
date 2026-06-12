$ErrorActionPreference = "Stop"

npx.cmd hardhat test
npx.cmd hardhat run scripts/gas-report.js
python dp/experiment.py --trials 100
python tee/pool_benchmark.py --requests 20
python tee/attack_simulation.py --trials 50
python tee/plot_attack_results.py
$env:TC_RUNS = "5"
$env:TC_VARIANTS = "TC-Full,NoZK,NoBudget,ACL-Only,OffChain"
$env:TC_TEE_ROWS = "1000000"
$env:TC_TEE_ROUNDS = "5"
$env:TC_PROVE_HASH_ROUNDS = "500000"
npx.cmd hardhat run benchmarks/pipeline-runner.js
Remove-Item Env:\TC_RUNS
Remove-Item Env:\TC_VARIANTS
Remove-Item Env:\TC_TEE_ROWS
Remove-Item Env:\TC_TEE_ROUNDS
Remove-Item Env:\TC_PROVE_HASH_ROUNDS
python benchmarks/summarize_results.py
python benchmarks/summarize_gas.py
python benchmarks/plot_figures.py
