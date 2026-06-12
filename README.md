# TrustCircuit

[![DOI](https://zenodo.org/badge/1245496520.svg)](https://doi.org/10.5281/zenodo.20669379)

TrustCircuit is a research prototype for accountable privacy-preserving data access. It combines blockchain-based access control and audit logs, differential privacy budget accounting, zero-knowledge compliance proofs, and a TEE worker simulator for off-chain computation.

The prototype follows a simple pipeline:

```text
Register -> Negotiate -> Compute -> Prove Compliance -> Audit & Consume
```

## Components

- Solidity smart contracts for data registration, access control, budget tracking, verification, and audit records.
- Differential privacy experiments with aggregate queries, Gaussian noise, and budget consumption.
- Circom/snarkjs zero-knowledge compliance proof flow.
- TEE worker simulator for request execution, attestation-like reports, and sealed witnesses, with experiments run on AWS Nitro as a TEE-like evaluation environment.
- Benchmark scripts for gas, latency, proof overhead, throughput, and privacy-utility evaluation.

## Quick Start

```bash
npm install
pip install -r requirements.txt
npm test
```

## Citation

This work is currently unpublished. If you use this repository, please cite the Zenodo archive:

```bibtex
@misc{huynh2026trustcircuit,
  title        = {TrustCircuit: Blockchain-Orchestrated Privacy-Preserving Data Circulation with Verifiable Compliance},
  author       = {Huynh, Bao and Tran, Tuan-Dung and Pham, Van-Hau},
  year         = {2026},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.20669380},
  url          = {https://doi.org/10.5281/zenodo.20669380},
  note         = {Unpublished research prototype}
}
```
