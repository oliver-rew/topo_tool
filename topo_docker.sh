#!/bin/bash

# run the scrip in docker with the provided args
docker run -it -v $(pwd):/workdir --workdir "/workdir" topo_tool:latest python3 topo.py $@
