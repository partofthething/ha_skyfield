"""Plots"""
import datetime

import matplotlib.pyplot as plt
import numpy as np

LABELS = [
    ("Sun", "gold", 500),
    ("Moon", "lightgrey", 300),
    ("Venus", "rosybrown", 20),
    ("Mars", "red", 20),
    ("Jupiter", "chocolate", 70),
    ("Saturn", "khaki", 50),
]


def plot_all_sun_paths(data):
    """Show where the sun goes throughout the year."""
    fig = plt.figure()
    ax = fig.add_subplot(111, projection="polar")  # pylint: disable=invalid-name
    alts, azis = zip(*data)
    ax.scatter(azis, alts, s=10, alpha=0.5)
    ax.set_theta_zero_location("S", offset=0)
    ax.set_rmax(90)
    plt.show()


def plot_sky(today, winter, summer, points, output=None, timelabel=None):
    """Make a figure with the sky and various planets/sun/moon."""
    visible = [np.linspace(0, 2 * np.pi, 200), [90.0 for _i in range(200)]]

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="polar")  # pylint: disable=invalid-name
    ax.set_axisbelow(True)
    ax.set_theta_direction(-1)
    ax.plot(*visible, "-", color="k", linewidth=3, alpha=1.0)
    for point, labelinfo in zip(points, LABELS):
        ax.scatter(
            *point, s=labelinfo[2], label=labelinfo[0], alpha=1.0, color=labelinfo[1], edgecolor="black"
        )
    ax.legend(loc="lower right")
    ax.plot(*today, "-", color="k", linewidth=1, alpha=0.8)
    ax.plot(*winter, "--", color="blue", linewidth=1, alpha=0.8)
    ax.plot(*summer, "--", color="green", linewidth=1, alpha=0.8)
    ax.set_theta_zero_location("S", offset=0)
    ax.set_rmax(90)
    ax.set_rgrids(
        np.linspace(0, 90, 10), [f"{int(f)}˚" for f in np.linspace(90, 0, 10)]
    )
    ax.set_thetagrids(
        np.linspace(0, 360.0, 9), ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    )
    if timelabel:
        ax.annotate(timelabel,
                xy=(.09, .07), xycoords='figure fraction',
                horizontalalignment='left', verticalalignment='top',
                fontsize=8)
    plt.tight_layout()
    if output is None:
        plt.show()
    else:
        # filename string or file-like object/buffer
        plt.savefig(output, format='png')
    plt.close()
