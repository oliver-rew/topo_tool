# topo_tool

A simple tool to convert GeoTIFF elevation files to STL mesh. Based HEAVILY on `phstl` (linked below). I even have my
own fork of `phstl` that fixes some issues (also linked below). Instead of using GDAL directly like `phstl`, this
tool uses `rasterio`.

https://github.com/anoved/phstl

https://github.com/oliver-rew/phstl

## Examples

First, get some elevation geotiffs from the national map downloader.
https://apps.nationalmap.gov/downloader/

- convert to STL with:
    - crop to coordinates
    - reproject to EPSG:3395
    - Resample 0.125 (downsample by 8x)
    - 2x Z scaling

```
$ python3.9 topo.py USGS_one_meter_x58y451_NY_CMPG_2013.tiff nyc.stl -z 2 -p EPSG:3395 -s 0.125 -c 40.700836 -74.020380 40.730494 -73.971060
```

- Run the same command, but with docker! This might be slower, but might be worth it if installing dependencies is a
  headache
    - pull the docker image
  ```
  $ docker pull oliverrew/topo_tool:latest
  ```
    - OR build it yourself. This could take a minute, but only has to be done once
  ```
  $ ./docker_build.sh
  ```
    - run it with the docker script
  ```
  $ ./topo_docker.sh data/USGS_one_meter_x58y451_NY_CMPG_2013.tiff nyc.stl -z 2 -p EPSG:3395 -s 0.125 -c 40.700836 -74.020380 40.730494 -73.971060
  ```

## TODO

- do final raster to STL conversion in parallel
- use a real STL library
- For cropping, instead of projecting to WGS84 for operation, convert the provided coordinates to the CRS of the source
  dataset and crop after any projection
