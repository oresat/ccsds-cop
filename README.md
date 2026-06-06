# ccsds-cop
A Python implementation of CCSDS Communications Operation Procedures (COP)

Currently, this includes the following:

- COP-1 services according to [CCSDS 232.1-B-2](https://ccsds.org/Pubs/232x1b2e2c1.pdf)
  - FARM-1
  - FOP-1

It does not contain implementations of the Higher or Lower Procedures which surround COP-1 services,
since these require spacecraft dependent implementations. For an example of ccsds-cop in action, see
the [OreSat C3](https://github.com/oresat/oresat-c3-software) repo.

# Quick Start

For users
```bash
$ pip install ccsds-cop
```
For developers:
```bash
$ pip install -e . --group dev
```

