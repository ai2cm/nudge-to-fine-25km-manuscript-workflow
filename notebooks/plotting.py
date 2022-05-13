import proplot


FONTSIZE = 8


def configure_style():
    proplot.config.use_style("default")
    proplot.rc["legend.facecolor"] = "white"  # Needed to prevent proplot errors
    proplot.rc["font.size"] = FONTSIZE
    proplot.rc["axes.titlesize"] = FONTSIZE
    proplot.rc["axes.labelsize"] = FONTSIZE
    proplot.rc["xtick.labelsize"] = FONTSIZE
    proplot.rc["ytick.labelsize"] = FONTSIZE
    proplot.rc["legend.fontsize"] = FONTSIZE
    proplot.rc["figure.titlesize"] = FONTSIZE
