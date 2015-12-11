from skimage import color
from sklearn import cluster
import numpy as np


class Analyzer:
    def __init__(self, grid, *args, **kwargs):
        pass

    @staticmethod
    def find_primary_colors(image, resolve_to_n_colors=20):
        k = resolve_to_n_colors
        lab = image.data_array_lab
        shape = lab.shape

        centroids, centroid_ixs, intertia = cluster.k_means(
            np.reshape(lab, (shape[0] * shape[1], shape[2])),
            k
        )

        hist = np.histogram(centroid_ixs, bins=k, range=[0, k])
        freqs = hist[0].tolist()
        bins = hist[1].astype(int).tolist()

        sorted_hist = sorted(
            zip(bins, freqs),
            key=lambda x: x[1],
            reverse=True
        )

        top_centroids_ixs = [x[0] for x in sorted_hist]
        top_colors_lab = [centroids[c] for c in top_centroids_ixs]
        lab_shaped = np.reshape(top_colors_lab, (1, k, 3))
        top_colors_rgb = (color.lab2rgb(lab_shaped) * 255).astype(int)

        return top_colors_rgb
