"""
Chart Generator Service

Generates various chart types using matplotlib.
Outputs PNG images that can be sent via any channel adapter.

Supported chart types:
- line: Time series, trends
- bar: Comparisons, categories
- pie: Proportions, percentages
- scatter: Correlations, distributions
- heatmap: Matrices, correlations
- gauge: Single metric with target
"""

import base64
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import tempfile

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.figure import Figure
import numpy as np

logger = logging.getLogger(__name__)

# Style configuration
DARK_STYLE = {
    'figure.facecolor': '#1e1e2e',
    'axes.facecolor': '#1e1e2e',
    'axes.edgecolor': '#cdd6f4',
    'axes.labelcolor': '#cdd6f4',
    'text.color': '#cdd6f4',
    'xtick.color': '#cdd6f4',
    'ytick.color': '#cdd6f4',
    'grid.color': '#45475a',
    'axes.grid': True,
    'grid.alpha': 0.3,
}

LIGHT_STYLE = {
    'figure.facecolor': '#ffffff',
    'axes.facecolor': '#ffffff',
    'axes.edgecolor': '#333333',
    'axes.labelcolor': '#333333',
    'text.color': '#333333',
    'xtick.color': '#333333',
    'ytick.color': '#333333',
    'grid.color': '#cccccc',
    'axes.grid': True,
    'grid.alpha': 0.3,
}

# Color palettes
COLORS = {
    'default': ['#89b4fa', '#f38ba8', '#a6e3a1', '#fab387', '#cba6f7', '#94e2d5', '#f9e2af', '#89dceb'],
    'warm': ['#f38ba8', '#fab387', '#f9e2af', '#eba0ac', '#f5c2e7', '#f2cdcd', '#f5e0dc', '#cdd6f4'],
    'cool': ['#89b4fa', '#89dceb', '#94e2d5', '#a6e3a1', '#cba6f7', '#b4befe', '#74c7ec', '#cdd6f4'],
    'mono': ['#cdd6f4', '#bac2de', '#a6adc8', '#9399b2', '#7f849c', '#6c7086', '#585b70', '#45475a'],
}


class ChartType(str, Enum):
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    GAUGE = "gauge"
    AREA = "area"
    HORIZONTAL_BAR = "horizontal_bar"


@dataclass
class ChartResult:
    """Result of chart generation."""
    success: bool
    image_bytes: Optional[bytes] = None
    image_base64: Optional[str] = None
    file_path: Optional[str] = None
    error: Optional[str] = None
    chart_type: str = ""
    width: int = 0
    height: int = 0


class ChartGenerator:
    """
    Generates charts from data using matplotlib.

    Usage:
        generator = ChartGenerator()
        result = generator.generate_line_chart(
            data={"labels": ["Jan", "Feb", "Mar"], "values": [10, 20, 15]},
            title="Monthly Sales"
        )
        # result.image_bytes contains PNG data
    """

    def __init__(self, style: str = "dark", dpi: int = 150):
        self.style = style
        self.dpi = dpi
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply the selected style."""
        style_dict = DARK_STYLE if self.style == "dark" else LIGHT_STYLE
        plt.rcParams.update(style_dict)
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.size'] = 10

    def _get_colors(self, palette: str = "default", n: int = 8) -> List[str]:
        """Get colors from palette."""
        colors = COLORS.get(palette, COLORS["default"])
        if n <= len(colors):
            return colors[:n]
        # Cycle colors if more needed
        return (colors * ((n // len(colors)) + 1))[:n]

    def _create_figure(self, figsize: Tuple[int, int] = (10, 6)) -> Tuple[Figure, Any]:
        """Create a new figure with axes."""
        fig, ax = plt.subplots(figsize=figsize)
        return fig, ax

    def _finalize_chart(
        self,
        fig: Figure,
        title: Optional[str] = None,
        save_to_file: bool = False,
    ) -> ChartResult:
        """Finalize chart and return result."""
        try:
            if title:
                fig.suptitle(title, fontsize=14, fontweight='bold', y=0.98)

            plt.tight_layout()

            # Save to bytes
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=self.dpi, bbox_inches='tight',
                       facecolor=fig.get_facecolor(), edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()

            # Optionally save to file
            file_path = None
            if save_to_file:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(image_bytes)
                    file_path = f.name

            plt.close(fig)

            return ChartResult(
                success=True,
                image_bytes=image_bytes,
                image_base64=base64.b64encode(image_bytes).decode('utf-8'),
                file_path=file_path,
                width=int(fig.get_figwidth() * self.dpi),
                height=int(fig.get_figheight() * self.dpi),
            )

        except Exception as e:
            plt.close(fig)
            logger.error(f"Failed to finalize chart: {e}")
            return ChartResult(success=False, error=str(e))

    # =========================================================================
    # Chart Types
    # =========================================================================

    def generate_line_chart(
        self,
        data: Dict[str, Any],
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        show_points: bool = True,
        fill: bool = False,
        palette: str = "default",
        figsize: Tuple[int, int] = (10, 6),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a line chart.

        Args:
            data: {"labels": [...], "values": [...]} or
                  {"labels": [...], "series": {"name1": [...], "name2": [...]}}
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label
            show_points: Show data points
            fill: Fill area under line
            palette: Color palette name
            figsize: Figure size (width, height) in inches
            save_to_file: Save to temporary file

        Returns:
            ChartResult with image data
        """
        try:
            fig, ax = self._create_figure(figsize)
            labels = data.get("labels", [])
            colors = self._get_colors(palette)

            if "series" in data:
                # Multiple series
                for i, (name, values) in enumerate(data["series"].items()):
                    color = colors[i % len(colors)]
                    line, = ax.plot(labels, values, color=color, linewidth=2, label=name)
                    if show_points:
                        ax.scatter(labels, values, color=color, s=50, zorder=5)
                    if fill:
                        ax.fill_between(labels, values, alpha=0.3, color=color)
                ax.legend()
            else:
                # Single series
                values = data.get("values", [])
                color = colors[0]
                ax.plot(labels, values, color=color, linewidth=2)
                if show_points:
                    ax.scatter(labels, values, color=color, s=50, zorder=5)
                if fill:
                    ax.fill_between(labels, values, alpha=0.3, color=color)

            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)

            # Rotate x labels if many
            if len(labels) > 6:
                plt.xticks(rotation=45, ha='right')

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.LINE.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate line chart: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.LINE.value)

    def generate_bar_chart(
        self,
        data: Dict[str, Any],
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        horizontal: bool = False,
        stacked: bool = False,
        palette: str = "default",
        figsize: Tuple[int, int] = (10, 6),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a bar chart.

        Args:
            data: {"labels": [...], "values": [...]} or
                  {"labels": [...], "series": {"name1": [...], "name2": [...]}}
            horizontal: Horizontal bars instead of vertical
            stacked: Stack multiple series
        """
        try:
            fig, ax = self._create_figure(figsize)
            labels = data.get("labels", [])
            colors = self._get_colors(palette)
            x = np.arange(len(labels))
            width = 0.35

            if "series" in data:
                series = data["series"]
                n_series = len(series)
                width = 0.8 / n_series

                bottoms = np.zeros(len(labels))
                for i, (name, values) in enumerate(series.items()):
                    color = colors[i % len(colors)]
                    if horizontal:
                        if stacked:
                            ax.barh(labels, values, left=bottoms, label=name, color=color)
                            bottoms += np.array(values)
                        else:
                            ax.barh(x + i * width - (n_series - 1) * width / 2, values,
                                   width, label=name, color=color)
                    else:
                        if stacked:
                            ax.bar(labels, values, bottom=bottoms, label=name, color=color)
                            bottoms += np.array(values)
                        else:
                            ax.bar(x + i * width - (n_series - 1) * width / 2, values,
                                  width, label=name, color=color)
                ax.legend()
                if not horizontal and not stacked:
                    ax.set_xticks(x)
                    ax.set_xticklabels(labels)
            else:
                values = data.get("values", [])
                color = colors[0]
                if horizontal:
                    ax.barh(labels, values, color=color)
                else:
                    ax.bar(labels, values, color=color)

            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)

            if len(labels) > 6 and not horizontal:
                plt.xticks(rotation=45, ha='right')

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.HORIZONTAL_BAR.value if horizontal else ChartType.BAR.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate bar chart: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.BAR.value)

    def generate_pie_chart(
        self,
        data: Dict[str, Any],
        title: Optional[str] = None,
        show_percentages: bool = True,
        show_labels: bool = True,
        explode_largest: bool = False,
        donut: bool = False,
        palette: str = "default",
        figsize: Tuple[int, int] = (8, 8),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a pie chart.

        Args:
            data: {"labels": [...], "values": [...]}
            show_percentages: Show percentage labels
            show_labels: Show category labels
            explode_largest: Explode the largest slice
            donut: Make it a donut chart
        """
        try:
            fig, ax = self._create_figure(figsize)
            labels = data.get("labels", [])
            values = data.get("values", [])
            colors = self._get_colors(palette, len(labels))

            explode = None
            if explode_largest and values:
                max_idx = values.index(max(values))
                explode = [0.05 if i == max_idx else 0 for i in range(len(values))]

            autopct = '%1.1f%%' if show_percentages else None
            wedge_labels = labels if show_labels else None

            wedges, texts, autotexts = ax.pie(
                values,
                labels=wedge_labels,
                autopct=autopct,
                colors=colors,
                explode=explode,
                startangle=90,
                pctdistance=0.75 if donut else 0.6,
            )

            if donut:
                centre_circle = plt.Circle((0, 0), 0.50, fc=DARK_STYLE['figure.facecolor']
                                          if self.style == 'dark' else 'white')
                ax.add_patch(centre_circle)

            # Style percentage text
            if autotexts:
                for autotext in autotexts:
                    autotext.set_color('white' if self.style == 'dark' else 'black')
                    autotext.set_fontsize(9)

            ax.axis('equal')

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.PIE.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate pie chart: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.PIE.value)

    def generate_scatter_chart(
        self,
        data: Dict[str, Any],
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        show_trend: bool = False,
        palette: str = "default",
        figsize: Tuple[int, int] = (10, 6),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a scatter plot.

        Args:
            data: {"x": [...], "y": [...]} or
                  {"series": {"name1": {"x": [...], "y": [...]}, ...}}
            show_trend: Show trend line
        """
        try:
            fig, ax = self._create_figure(figsize)
            colors = self._get_colors(palette)

            if "series" in data:
                for i, (name, series_data) in enumerate(data["series"].items()):
                    x = series_data.get("x", [])
                    y = series_data.get("y", [])
                    color = colors[i % len(colors)]
                    ax.scatter(x, y, c=color, label=name, alpha=0.7, s=50)
                    if show_trend and len(x) > 1:
                        z = np.polyfit(x, y, 1)
                        p = np.poly1d(z)
                        ax.plot(x, p(x), color=color, linestyle='--', alpha=0.5)
                ax.legend()
            else:
                x = data.get("x", [])
                y = data.get("y", [])
                ax.scatter(x, y, c=colors[0], alpha=0.7, s=50)
                if show_trend and len(x) > 1:
                    z = np.polyfit(x, y, 1)
                    p = np.poly1d(z)
                    ax.plot(sorted(x), p(sorted(x)), color=colors[1], linestyle='--', alpha=0.7)

            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.SCATTER.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate scatter chart: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.SCATTER.value)

    def generate_heatmap(
        self,
        data: Dict[str, Any],
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        show_values: bool = True,
        cmap: str = "coolwarm",
        figsize: Tuple[int, int] = (10, 8),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a heatmap.

        Args:
            data: {"matrix": [[...], [...]], "x_labels": [...], "y_labels": [...]}
            show_values: Show values in cells
            cmap: Colormap name
        """
        try:
            fig, ax = self._create_figure(figsize)
            matrix = np.array(data.get("matrix", []))
            x_labels = data.get("x_labels", [])
            y_labels = data.get("y_labels", [])

            im = ax.imshow(matrix, cmap=cmap, aspect='auto')

            # Colorbar
            cbar = fig.colorbar(im, ax=ax)
            cbar.ax.yaxis.set_tick_params(color=DARK_STYLE['text.color'] if self.style == 'dark' else 'black')

            # Labels
            if x_labels:
                ax.set_xticks(np.arange(len(x_labels)))
                ax.set_xticklabels(x_labels)
            if y_labels:
                ax.set_yticks(np.arange(len(y_labels)))
                ax.set_yticklabels(y_labels)

            # Show values
            if show_values:
                for i in range(matrix.shape[0]):
                    for j in range(matrix.shape[1]):
                        val = matrix[i, j]
                        text_color = 'white' if abs(val) > (matrix.max() - matrix.min()) / 2 else 'black'
                        ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                               color=text_color, fontsize=8)

            if x_label:
                ax.set_xlabel(x_label)
            if y_label:
                ax.set_ylabel(y_label)

            plt.xticks(rotation=45, ha='right')

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.HEATMAP.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate heatmap: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.HEATMAP.value)

    def generate_gauge(
        self,
        value: float,
        max_value: float = 100,
        title: Optional[str] = None,
        label: Optional[str] = None,
        thresholds: Optional[Dict[str, float]] = None,
        figsize: Tuple[int, int] = (6, 4),
        save_to_file: bool = False,
    ) -> ChartResult:
        """
        Generate a gauge chart.

        Args:
            value: Current value
            max_value: Maximum value
            title: Chart title
            label: Value label (e.g., "CPU Usage")
            thresholds: {"warning": 70, "critical": 90} for color zones
        """
        try:
            fig, ax = self._create_figure(figsize)

            # Default thresholds
            if thresholds is None:
                thresholds = {"warning": max_value * 0.7, "critical": max_value * 0.9}

            # Draw gauge background
            theta = np.linspace(np.pi, 0, 100)
            r_outer = 1.0
            r_inner = 0.7

            # Color zones
            warning = thresholds.get("warning", max_value * 0.7)
            critical = thresholds.get("critical", max_value * 0.9)

            colors_zones = ['#a6e3a1', '#f9e2af', '#f38ba8']  # green, yellow, red
            zone_ends = [warning / max_value, critical / max_value, 1.0]
            zone_start = 0

            for i, zone_end in enumerate(zone_ends):
                theta_start = np.pi - zone_start * np.pi
                theta_end = np.pi - zone_end * np.pi
                theta_zone = np.linspace(theta_start, theta_end, 50)

                ax.fill_between(
                    theta_zone, r_inner, r_outer,
                    color=colors_zones[i], alpha=0.3,
                    transform=ax.transData + matplotlib.transforms.Affine2D().scale(1, 1)
                )
                zone_start = zone_end

            # Draw arc outline
            for r in [r_inner, r_outer]:
                x = r * np.cos(theta)
                y = r * np.sin(theta)
                ax.plot(x, y, color=DARK_STYLE['axes.edgecolor'] if self.style == 'dark' else '#333', linewidth=1)

            # Draw needle
            angle = np.pi - (value / max_value) * np.pi
            needle_length = 0.85
            ax.arrow(0, 0, needle_length * np.cos(angle), needle_length * np.sin(angle),
                    head_width=0.05, head_length=0.03, fc='white' if self.style == 'dark' else 'black',
                    ec='white' if self.style == 'dark' else 'black')

            # Center circle
            circle = plt.Circle((0, 0), 0.1, color=DARK_STYLE['axes.edgecolor'] if self.style == 'dark' else '#333')
            ax.add_patch(circle)

            # Value text
            ax.text(0, -0.3, f'{value:.1f}', ha='center', va='center', fontsize=24, fontweight='bold',
                   color=DARK_STYLE['text.color'] if self.style == 'dark' else 'black')
            if label:
                ax.text(0, -0.5, label, ha='center', va='center', fontsize=12,
                       color=DARK_STYLE['text.color'] if self.style == 'dark' else 'black')

            # Scale labels
            for val, angle_pos in [(0, np.pi), (max_value / 2, np.pi / 2), (max_value, 0)]:
                x = 1.15 * np.cos(angle_pos)
                y = 1.15 * np.sin(angle_pos)
                ax.text(x, y, f'{val:.0f}', ha='center', va='center', fontsize=10,
                       color=DARK_STYLE['text.color'] if self.style == 'dark' else 'black')

            ax.set_xlim(-1.5, 1.5)
            ax.set_ylim(-0.7, 1.3)
            ax.set_aspect('equal')
            ax.axis('off')

            result = self._finalize_chart(fig, title, save_to_file)
            result.chart_type = ChartType.GAUGE.value
            return result

        except Exception as e:
            logger.error(f"Failed to generate gauge: {e}")
            return ChartResult(success=False, error=str(e), chart_type=ChartType.GAUGE.value)

    # =========================================================================
    # Universal Generator
    # =========================================================================

    def generate(
        self,
        chart_type: str,
        data: Dict[str, Any],
        **kwargs
    ) -> ChartResult:
        """
        Generate any chart type.

        Args:
            chart_type: One of "line", "bar", "pie", "scatter", "heatmap", "gauge"
            data: Chart data
            **kwargs: Additional arguments for the specific chart type

        Returns:
            ChartResult
        """
        chart_type = chart_type.lower()

        if chart_type == "line":
            return self.generate_line_chart(data, **kwargs)
        elif chart_type in ("bar", "horizontal_bar"):
            kwargs["horizontal"] = chart_type == "horizontal_bar"
            return self.generate_bar_chart(data, **kwargs)
        elif chart_type == "pie":
            return self.generate_pie_chart(data, **kwargs)
        elif chart_type == "scatter":
            return self.generate_scatter_chart(data, **kwargs)
        elif chart_type == "heatmap":
            return self.generate_heatmap(data, **kwargs)
        elif chart_type == "gauge":
            value = data.get("value", 0)
            max_value = data.get("max_value", 100)
            return self.generate_gauge(value, max_value, **kwargs)
        else:
            return ChartResult(
                success=False,
                error=f"Unknown chart type: {chart_type}. Supported: line, bar, pie, scatter, heatmap, gauge"
            )


# Singleton instance
_chart_generator: Optional[ChartGenerator] = None


def get_chart_generator(style: str = "dark") -> ChartGenerator:
    """Get the singleton ChartGenerator instance."""
    global _chart_generator
    if _chart_generator is None:
        _chart_generator = ChartGenerator(style=style)
    return _chart_generator
