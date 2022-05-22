import argparse
import logging

from matplotlib import pyplot
import numpy as np

from struct import pack
import rasterio
import rasterio.mask as mask
from rasterio.io import MemoryFile
from rasterio.warp import calculate_default_transform, reproject, Resampling

logging.basicConfig(level=logging.INFO)


def resample(src, factor):
    meta = src.meta.copy()
    # resample data to target shape
    data = src.read(
        out_shape=(
            src.count,
            int(src.height * factor),
            int(src.width * factor)
        ),
        resampling=Resampling.bilinear
    )

    print("SHAPE:", data.shape)
    # scale image transform
    transform = src.transform * src.transform.scale(
        (src.width / data.shape[-1]),
        (src.height / data.shape[-2])
    )

    meta.update({"driver": "GTiff",
                 "height": data.shape[-2],
                 "width": data.shape[-1],
                 "transform": transform})

    m = MemoryFile().open(**meta)
    m.write(data)
    return m


def reproject_ds(src, dest_crs):
    # reproject
    transform, width, height = calculate_default_transform(
        src.crs, dest_crs, src.width, src.height, *src.bounds)
    kwargs = src.meta.copy()
    kwargs.update({
        'crs': dest_crs,
        'transform': transform,
        'width': width,
        'height': height
    })

    dst = MemoryFile().open(**kwargs)

    for i in range(1, src.count + 1):
        reproject(
            source=rasterio.band(src, i),
            destination=rasterio.band(dst, i),
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dest_crs,
            resampling=Resampling.nearest)

    return dst


def crop_corners_to_geojson(crop):
    # 'crop' in format [lower left lat, lower left long, upper right lat, upper right long]
    lower_left_lat = crop[0]
    lower_left_lon = crop[1]
    upper_right_lat = crop[2]
    upper_right_lon = crop[3]
    return [{'type': 'Polygon',
             'coordinates': [
                 [
                     # coord in lon/lat (not lat/long)
                     [lower_left_lon, lower_left_lat],  # lower left
                     [upper_right_lon, lower_left_lat],  # lower right
                     [upper_right_lon, upper_right_lat],  # upper right
                     [lower_left_lon, upper_right_lat],  # upper left
                     [lower_left_lon, lower_left_lat],  # lower left
                 ]
             ]
             }]


def crop(src, crop_args):
    crop = crop_corners_to_geojson(crop_args)
    out_image, out_transform = mask.mask(src, crop, crop=True, nodata=0)
    meta = src.meta.copy()
    meta.update({"driver": "GTiff",
                 "height": out_image.shape[1],
                 "width": out_image.shape[2],
                 "transform": out_transform})

    m = MemoryFile().open(**meta)
    m.write(out_image)
    return m


#
# NormalVector
#
# Calculate the normal vector of a triangle. (Unit vector perpendicular to
# triangle surface, pointing away from the "outer" face of the surface.)
# Computed using 32-bit float operations for consistency with other tools.
#
# Parameters:
#  triangle vertices (nested x y z tuples)
#
# Returns:
#  normal vector (x y z tuple)
#
def NormalVector(t):
    (ax, ay, az) = t[0]
    (bx, by, bz) = t[1]
    (cx, cy, cz) = t[2]

    # first edge
    e1x = np.float32(ax) - np.float32(bx)
    e1y = np.float32(ay) - np.float32(by)
    e1z = np.float32(az) - np.float32(bz)

    # second edge
    e2x = np.float32(bx) - np.float32(cx)
    e2y = np.float32(by) - np.float32(cy)
    e2z = np.float32(bz) - np.float32(cz)

    # cross product
    cpx = np.float32(e1y * e2z) - np.float32(e1z * e2y)
    cpy = np.float32(e1z * e2x) - np.float32(e1x * e2z)
    cpz = np.float32(e1x * e2y) - np.float32(e1y * e2x)

    # return cross product vector normalized to unit length
    mag = np.sqrt(np.power(cpx, 2) + np.power(cpy, 2) + np.power(cpz, 2))
    return (cpx / mag, cpy / mag, cpz / mag)


# stlwriter is a simple class for writing binary STL meshes.
# Class instances are constructed with a predicted face count.
# The output file header is overwritten upon completion with
# the actual face count.
class stlwriter():

    # path: output binary stl file path
    # facet_count: predicted number of facets
    def __init__(self, path, facet_count=0):
        self.f = open(path, 'wb')

        # track number of facets actually written
        self.written = 0

        # write binary stl header with predicted facet count
        self.f.write(b'\0' * 80)
        # (facet count is little endian 4 byte unsigned int)
        self.f.write(pack('<I', facet_count))

    # t: ((ax, ay, az), (bx, by, bz), (cx, cy, cz))
    def add_facet(self, t):
        # facet normals and vectors are little endian 4 byte float triplets
        # strictly speaking, we don't need to compute NormalVector,
        # as other tools could be used to update the output mesh.
        self.f.write(pack('<3f', *NormalVector(t)))
        for vertex in t:
            self.f.write(pack('<3f', *vertex))
        # facet records conclude with two null bytes (unused "attributes")
        self.f.write(b'\0\0')
        self.written += 1

    def done(self):
        # update final facet count in header before closing file
        self.f.seek(80)
        self.f.write(pack('<I', self.written))
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.done()


# float32 wraps np.float32 but returns 0 for infinity numbers, which we often
# get from np.float32 for very small numbers
# TODO this is jank
def float32(x):
    f = np.float32(x)
    if np.isinf(f):
        return np.float32(0)
    return f


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description='Convert GeoTIFF heightmap to an STL')
    ap.add_argument('RASTER', help='Input heightmap image')
    ap.add_argument('STL', help='Output STL path')
    ap.add_argument('-p', '--reproject', action='store', default=None, type=str, help='Reprojection EPSG')
    ap.add_argument('-s', '--resample', action='store', default=None, type=float,
                    help='Resample factor. ex: 0.5 = downsample by 2, ex: 2.0 = upsample by 2')
    ap.add_argument('-c', '--crop', action='store', default=None, type=float, nargs=4,
                    help='Opposing corner coordinates. Format: <lower-left-lat> <lower-left-lon> <upper-right-lat> <upper-right-lon>)',
                    metavar="deg")
    ap.add_argument('-S', '--show', action='store_true', default=False, help='plot the final area')
    ap.add_argument('-z', '--zscale', action='store', default=1.0, type=float, help='Z scale modifier')
    ap.add_argument('-f', '--force', action='store_true', default=False, help='Force unprojected/unitless data')
    args = ap.parse_args()

    with rasterio.open(args.RASTER) as src:
        # arg order is crop, resample, and reproject because they are least to
        # most expensive operations. Reducing size with crop and resample, will
        # reduce reprojection time
        if args.crop:
            # TODO SO JANK project to a CRS that uses degrees so we can crop, then project back
            # EPSG:4326 is WGS84, a good global, degrees CRS system to use for
            # cropping to lat/long
            global_crs = "EPSG:4326"
            orig_crs = src.crs
            src = reproject_ds(src, "EPSG:4326")
            logging.info(f"cropping to {args.crop}")
            src = crop(src, args.crop)
            src = reproject_ds(src, orig_crs)

        # resample
        if args.resample:
            logging.info(f"resampling at {args.resample}")
            logging.info(f"original (width, height): ({src.width}, {src.height})")
            src = resample(src, args.resample)
            logging.info(f"new (width, height): ({src.width}, {src.height})")

        # reproject
        if args.reproject:
            logging.info(f"reprojecting to {args.reproject}")
            src = reproject_ds(src, args.reproject)

        trans = src.transform
        logging.info("transform: {}".format(repr(trans).replace("\n", "").replace(" ", "")))

        profile = src.profile
        nodata = profile["nodata"]
        logging.info(f"nodata value: {nodata}")

        # function to skip if nodata value
        skip = lambda x: x == nodata

        crs = profile["crs"]
        logging.info(f"crs: {crs}")
        logging.info(f"units: {crs.linear_units}")
        logging.info(f"resolution: {src.res}")
        logging.info(f"projected: {crs.is_projected}")
        logging.info(f"bounds: {src.bounds}")

        # dump all attrs
        # for name in dir(src):
        #     attr = getattr(src, name)
        #     try:
        #         if callable(attr):
        #             print(f"=== {name} : {attr()}")
        #         else:
        #             print(f"=== {name} : {attr}")
        #     except Exception as e:
        #         print(f"ERROR[{name}]: {e}")

        # fail if the dataset is not projected or units are unknown. In my
        # experience, the unprojected/unitless data sets produces undesirable
        # output. This was because the linear units were most likely degrees,
        # but the vertical units were metres, but since that could be
        # determined, that scale was way off and required a significant z
        # scaling factor to fix. It is much better to just reproject
        if not crs.is_projected or crs.linear_units == "unknown":
            warning = (f"CRS is not projected or units are unknown. While possible to complete, the results" +
                       f" will likely be undesirable. It is suggested you project the dataset with the" +
                       f" '-r|--reproject' flag. example: '-r EPSG:3395'. This check can be overridden with" +
                       f"the '-f|--force' flag")
            if args.force:
                logging.warning(warning)
            else:
                raise Exception(warning)

        # read band #1 to get the actual pixel array
        # TODO this might not always be band #1?
        pixels = src.read(1)

    # output mesh dimensions are one row and column less than raster window
    mw = pixels.shape[1] - 1  # width X
    mh = pixels.shape[0] - 1  # height Y
    facetcount = mw * mh * 2
    logging.info(f"mw,mh = ({mw},{mh})")
    logging.info(f"stl facets = {facetcount}")

    xmin, ymin, zmin = 0, 0, 0

    # x and y scales come from Affine transformation.
    xscale = trans.a
    yscale = trans.e
    zscale = trans.i * args.zscale
    logging.info(f"xscale: {xscale} yscale: {yscale} zscale: {zscale}")

    # I basically store this whole routine from phstl
    with stlwriter(args.STL, facetcount) as mesh:
        for y in range(mh):
            progress = (y / mh) * 100
            print(f"Writing STL: {progress:.2f}%", end='\r')

            for x in range(mw):

                # Elevation values of this pixel (a) and its neighbors (b, c, and d).
                av = pixels[y][x]
                bv = pixels[y + 1][x]
                cv = pixels[y][x + 1]
                dv = pixels[y + 1][x + 1]

                # Apply transforms to obtain output mesh coordinates of the
                # four corners composed of raster points a (x, y), b, c,
                # and d (x + 1, y + 1):
                #
                # a-c   a-c     c
                # |/| = |/  +  /|
                # b-d   b     b-d

                # Points b and c are required for both facets, so if either
                # are unavailable, we can skip this pixel altogether.
                if skip(bv) or skip(cv):
                    continue

                # TODO for each axis I am only considering one aspect of the Affine transformation,
                # but that probably wont work out for non rectangles. See phstl
                b = (
                    float32(xscale * (xmin + x)),
                    float32(yscale * (ymin + y + 1)),
                    float32(zscale * (float(bv) - zmin))
                )

                c = (
                    float32(xscale * (xmin + x + 1)),
                    float32(yscale * (ymin + y)),
                    float32(zscale * (float(cv) - zmin))
                )

                if not skip(av):
                    a = (
                        float32(xscale * (xmin + x)),
                        float32(yscale * (ymin + y)),
                        float32(zscale * (float(av) - zmin))
                    )
                    mesh.add_facet((a, b, c))

                if not skip(dv):
                    d = (
                        float32(xscale * (xmin + x + 1)),
                        float32(yscale * (ymin + y + 1)),
                        float32(zscale * (float(dv) - zmin))
                    )
                    mesh.add_facet((d, c, b))

    # show it
    if args.show:
        pyplot.imshow(src.read(1), cmap='pink')
        pyplot.show()
