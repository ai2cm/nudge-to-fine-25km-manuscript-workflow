import fv3viz
import matplotlib.legend
import matplotlib.lines
import pandas as pd
import proplot
import seaborn as sns
import vcm.catalog


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


def get_legend(ax):
    """For when ax.get_legend() does not work...I think this is a proplot issue."""
    for child in ax.get_children():
        if isinstance(child, matplotlib.legend.Legend):
            return child


def plot_map(ax, ds, variable, vmin, vmax, **kwargs):
    grid = vcm.catalog.catalog["grid/c48"].to_dask()
    ds = ds.merge(grid)
    _, _, (p, ), _, _ = fv3viz.plot_cube(
        ds,
        variable,
        ax=ax,
        vmin=vmin,
        vmax=vmax,
        cmap="RdBu_r",
        colorbar=False,
        **kwargs
    )
    return p


def legend(ax, labels, palette, **kwargs):
    handles = dummy_handles(labels, palette)
    ax.legend(handles=handles, labels=labels, **kwargs)


def dummy_handles(labels, palette, linestyle="None", marker="o", markersize=7):
    handles = []
    for color, label in zip(palette, labels):
        h = matplotlib.lines.Line2D(
                [],
                [],
                color=color,
                label=label,
                linestyle=linestyle,
                marker=marker,
                markersize=markersize,
        )
        handles.append(h)
    return handles


KINDS = {
    "Baseline": "baseline",
    "ML-corrected": "ml-corrected",
    "Nudged": "nudged",
    "Fine resolution": "fine-resolution"
}


def infer_run_kind(series):
    """A run 'kind' is the category of configuration it corresponds with.  This
    is so that we can group ML-corrected runs together if we would like.
    """
    result = []
    for label in series:
        for key, kind in KINDS.items():
            if key in label:
                result.append(kind)
                break
    return result


def to_plottable_dataframe(metrics, variable, region, metric, sample_mask):
    series = (
        metrics.isel(sample=sample_mask)
        .sel(metric=metric, region=region)[variable]
        .to_pandas()
        .stack()
        .stack()
    )
    df = pd.DataFrame(series, columns=[variable]).reset_index()
    df["kind"] = infer_run_kind(df["configuration"])
    return df


def swarmplot_by_category(ax, df, field, base_palette, add_legend=False, legend_kwargs=None, **kwargs):
    kind_config_pairs = sorted(list(set(list(zip(df["kind"], df["configuration"])))), key=lambda x: x[0] + x[1])
    kinds = sorted(df["kind"].unique())
    configurations = [configuration for _, configuration in kind_config_pairs]
    for (kind, configuration), color in zip(kind_config_pairs, base_palette):
        palette = ["#000000" for kind in kinds]
        palette[kinds.index(kind)] = color
        mask = (df["kind"] == kind) & (df["configuration"] == configuration)
        masked_df = df.copy(deep=True)
        masked_df[field] = masked_df[field].where(mask)
        sns.swarmplot(ax=ax, data=masked_df, hue="kind", y=field, palette=palette, **kwargs)
        
    get_legend(ax).set_visible(False)

    if add_legend:
        if legend_kwargs is None:
            legend_kwargs = {}
        legend(ax, configurations, base_palette, **legend_kwargs)
