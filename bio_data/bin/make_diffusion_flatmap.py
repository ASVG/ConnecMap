#!/usr/bin/env python
import h5py
import numpy

from diffusion_mapping import flatten_pathway
from projection_voxels import CachedProjections, FlattenedProjections

vxl_shape = (132, 80, 114)
vxl_offset = numpy.array([0., 0., 0.])
vxl_dims = numpy.array([100., 100., 100.])


def write_flatmap(flattened_regions, considered_regions, three_d_coords, flatmap_coords, output_path):
    three_d_coords = (three_d_coords / vxl_dims).astype(int)  # TODO: Better way
    flat_str = ",".join(sorted(flattened_regions))
    cons_str = ",".join(sorted(considered_regions))
    from voxcell import VoxelData

    if os.path.isfile(output_path):
        existing_map = VoxelData.load_nrrd(output_path).raw
    else:
        existing_map = numpy.NaN * numpy.ones(vxl_shape + (flatmap_coords.shape[1],), dtype=float)
    existing_map[three_d_coords[:, 0], three_d_coords[:, 1], three_d_coords[:, 2]] = flatmap_coords

    print("Writing flatmap for regions {src} via {tgt} to {fn}".format(src=flat_str,
                                                                       tgt=cons_str,
                                                                       fn=output_path)
          )

    my_map = VoxelData(existing_map, voxel_dimensions=tuple(vxl_dims),
                       offset=tuple(vxl_offset))  # map in .nrrd format
    VoxelData.save_nrrd(my_map, output_path)


def normalize_fm_coordinates(fm_coords, normalize_args=-1, multiply=numpy.NaN):
    fm_coords = fm_coords - numpy.nanmin(fm_coords, axis=0, keepdims=True)
    if fm_coords.shape[1] == 2:
        normalize_spread = numpy.array(normalize_args['normalize_spread'])
        offsets = numpy.array(normalize_args['normalize_offsets'])
    elif fm_coords.shape[1] > 2:
        normalize_spread = numpy.repeat(normalize_args['normalize_spread'][0], fm_coords.shape[1])
        offsets = numpy.repeat(normalize_args['normalize_offsets'][0], fm_coords.shape[1])
    multiply = numpy.array(multiply)
    if numpy.all(normalize_spread > 0):
        fm_coords = numpy.array(normalize_spread) * fm_coords / (numpy.nanmax(fm_coords, axis=0, keepdims=True) -
                                                                 numpy.nanmin(fm_coords, axis=0, keepdims=True))
        fm_coords = offsets + fm_coords
    if not numpy.any(numpy.isnan(multiply)):
        fm_coords = numpy.array(multiply) * fm_coords
    return fm_coords


if __name__ == "__main__":
    import argparse, os, json
    parser = argparse.ArgumentParser(description='Build a diffusion based flatmap\n')

    parser.add_argument('--allen_cache', help='Path to the manifest file of the Allen Institutes connectivity model', default=None)
    parser.add_argument('--h5_cache', help='Path to the hdf5 cache file to use')
    parser.add_argument('--output_path', help='Flatmap output path', default='./db_flatmap.nrrd')
    parser.add_argument('--region_file', help='Json file that specifies which regions to flatten')
    parser.add_argument('--characterize', help='Set path to output file for the fraction variance explained by the selected components',
                        default=None)
    args = parser.parse_args()

    if args.allen_cache is not None:
        import mcmodels
        allen_data = mcmodels.core.VoxelModelCache(manifest_file=args.allen_cache)
    else:
        allen_data = None

    cache = CachedProjections(allen_data=allen_data, cache_file=args.h5_cache, grow_cache=True)

    output_path = args.output_path

    assert os.path.isfile(args.region_file), "Cannot find region file: {0}".format(str(args.region_file))
    with open(args.region_file, "r") as fid:
        regions = json.load(fid)

    if not isinstance(regions, list):
        regions = [regions]
    char = []
    for _regions in regions:
        tgt_options = _regions["connectivity_target"]
        components_to_use = _regions["components"]
        n_components = numpy.max(components_to_use) + 1
        if args.characterize is not None:
            print("Variance characterization requested. Setting number of components from {0} to 100".format(n_components))
            n_components = 100  # This is in the hope that 100 components are always enough to capture all variance... We test this later
        _, _, _, coords_final, embed_coords_final, embed_stats = flatten_pathway(cache,
                                                                       _regions["flatten"],
                                                                       tgt_options["considered_regions"],
                                                                       n_components=n_components,
                                                                       diffusion_time=1,
                                                                       direction=tgt_options["direction"])
        if args.characterize:
            if embed_stats["n_components_auto"] >= (embed_stats["n_components"] - 2):
                # If this is true then even the last component is stronger than 0.05 of the first.
                print("Warning: {0} components were apparently not enough to characterize the full variance. Resulting variance fractions not valid".format(embed_stats["n_components"]))
            component_lambda_ratios = embed_stats["lambdas"][components_to_use] / embed_stats["lambdas"].sum()

            char.append(dict({"region": _regions["flatten"][0], # adding lambdas for each region
                              "selected_lambda_ratios": list(component_lambda_ratios),
                              "lambdas": list(embed_stats["lambdas"]})))
                
        embed_coords_final = embed_coords_final[:, components_to_use]
        embed_coords_final = normalize_fm_coordinates(embed_coords_final, _regions.get("normalization_args", {}))

        write_flatmap(_regions["flatten"], tgt_options["considered_regions"],
                      coords_final, embed_coords_final, output_path)
    if args.characterize: # saving diffusion results
        with open(args.characterize, "w") as fid:
            json.dump(char, fid)


