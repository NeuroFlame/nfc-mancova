"""
HTML report generator for nfc-mancova central aggregation results.
"""

import base64
import glob as _glob
import os
from typing import Any, Dict, List


def generate_report(
    output_dir: str,
    global_results: Dict[str, Any],
    site_results: List[Dict[str, Any]],
    site_names: List[str],
    parameters: Dict[str, Any],
) -> str:
    """Build a self-contained HTML report and store it in global_results['report_html'].

    Images are embedded as base64 data URIs so the report is readable anywhere —
    at site output dirs in production or the aggregation dir in the simulator.
    Also writes a copy to output_dir/index.html for convenience.
    """
    html = _build_report(global_results, site_results, site_names, parameters)
    global_results["report_html"] = html
    out_path = os.path.join(output_dir, "index.html")
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_report(
    r: Dict[str, Any],
    site_results: List[Dict[str, Any]],
    site_names: List[str],
    parameters: Dict[str, Any],
) -> str:
    """Build a fully self-contained HTML string (images embedded as base64)."""
    num_sites = r.get("num_sites", 0)
    num_subjects = r.get("num_subjects", 0)
    num_covariates = r.get("num_covariates", 0)
    features = r.get("features", [])
    aggregation_dir = r.get("aggregation_directory", "")
    status = r.get("status", "unknown")

    # --- Study overview cards ---
    cards = f"""
    <div class="card-row">
      <div class="card accent">
        <div class="card-label">Sites</div>
        <div class="card-value">{num_sites}</div>
        <div class="card-sub">Contributing sites</div>
      </div>
      <div class="card accent">
        <div class="card-label">Subjects</div>
        <div class="card-value">{num_subjects}</div>
        <div class="card-sub">Total across all sites</div>
      </div>
      <div class="card">
        <div class="card-label">Covariates</div>
        <div class="card-value">{num_covariates}</div>
        <div class="card-sub">In pooled model</div>
      </div>
      <div class="card">
        <div class="card-label">Features</div>
        <div class="card-value">{len(features)}</div>
        <div class="card-sub">{", ".join(features) if features else "none"}</div>
      </div>
    </div>"""

    # --- Per-site subject counts ---
    site_rows = ""
    for i, sr in enumerate(site_results):
        n = sr.get("num_subjects", 0)
        name = site_names[i] if i < len(site_names) else f"Site {i + 1}"
        cov_count = sr.get("num_covariates", 0)
        status_badge = (
            '<span class="badge-ok">completed</span>'
            if sr.get("status") == "completed"
            else '<span class="badge-warn">partial</span>'
        )
        site_rows += f"""
        <tr>
          <td>{name}</td>
          <td>{n}</td>
          <td>{cov_count}</td>
          <td>{status_badge}</td>
        </tr>"""

    site_table = f"""
    <h2>Site Participation</h2>
    <table>
      <thead>
        <tr><th>Site</th><th>Subjects</th><th>Covariates</th><th>Status</th></tr>
      </thead>
      <tbody>{site_rows}</tbody>
    </table>""" if site_rows else ""

    # --- Group ICA (per-site, fixed relative paths) ---
    skip_gica = parameters.get("skip_gica", False)
    if not skip_gica:
        analyses_html = "<h2>Group ICA</h2>"
        analyses_html += """
    <div class="analysis-block">
      <div class="analysis-title">Site-level Group ICA</div>
      <p>Independent component analysis run locally at this site. Reports below are specific to this site.</p>
      <ul class="report-links">
        <li><a href="coinstac-gica/coinstac-gica_gica_results/icatb_gica_html_report.html" target="_blank">ICA Results Report</a></li>
        <li><a href="coinstac-gica/network_summary/coinstac-gica_network_summary_network_summary.html" target="_blank">Network Summary</a></li>
      </ul>
    </div>"""
    else:
        analyses_html = "<h2>Analyses</h2>"

    # --- Univariate Tests ---
    univariate_paths = r.get("univariate_result_paths", {})
    if r.get("run_univariate_tests"):
        univariate_test_list = parameters.get("univariate_test_list", [])
        test_config_rows = ""
        for spec in univariate_test_list:
            test_type = list(spec.keys())[0]
            test_params = spec[test_type]
            if test_type == "regression" and isinstance(test_params, dict):
                for outcome, covs in test_params.items():
                    covs_str = ", ".join(covs) if isinstance(covs, list) else str(covs)
                    test_config_rows += f"<tr><td>Regression</td><td>{outcome}</td><td>{covs_str}</td></tr>"
            else:
                test_config_rows += f"<tr><td>{test_type}</td><td colspan='2'>{test_params}</td></tr>"

        test_config_table = f"""
        <table>
          <thead><tr><th>Test Type</th><th>Outcome</th><th>Covariates</th></tr></thead>
          <tbody>{test_config_rows}</tbody>
        </table>""" if test_config_rows else ""

        site_stat_rows = ""
        for i, sr in enumerate(site_results):
            n_files = len(sr.get("univariate_stat_info_files", []))
            n_subj = sr.get("num_subjects", 0)
            name = site_names[i] if i < len(site_names) else f"Site {i + 1}"
            site_stat_rows += f"<tr><td>{name}</td><td>{n_subj}</td><td>{'✓' if n_files > 0 else '—'}</td></tr>"

        site_stat_table = f"""
        <table>
          <thead><tr><th>Site</th><th>Subjects</th><th>Stats contributed</th></tr></thead>
          <tbody>{site_stat_rows}</tbody>
        </table>""" if site_stat_rows else ""

        if univariate_paths:
            inner = ""
            for test_name, paths in univariate_paths.items():
                gift_htmls = [p for p in paths if p.endswith(".html") and "results_summary" in p]
                if gift_htmls:
                    inner += f"<p><strong>{test_name}</strong></p>"
                    inner += _embed_gift_results(gift_htmls[0], aggregation_dir)
                else:
                    report_links = _report_links(paths, aggregation_dir)
                    inner += f"<p><strong>{test_name}</strong></p>{report_links}"
            analyses_html += f"""
    <h2>Univariate Tests</h2>
    <div class="analysis-block">
      <div class="analysis-title">Globally Aggregated</div>
      {test_config_table}
      {site_stat_table}
      {inner}
    </div>"""
        else:
            analyses_html += f"""
    <h2>Univariate Tests</h2>
    <div class="analysis-block">
      <div class="analysis-title">Configuration</div>
      {test_config_table}
      {site_stat_table}
      <p class="muted-text">Global aggregation did not produce output files.</p>
    </div>"""

    # --- Multivariate MANCOVA ---
    multivariate_paths = r.get("multivariate_result_paths", [])
    if r.get("run_mancova") and multivariate_paths:
        gift_htmls = [p for p in multivariate_paths if p.endswith(".html") and "results_summary" in p]
        if gift_htmls:
            inner = _embed_gift_results(gift_htmls[0], aggregation_dir)
        else:
            inner = '<p class="muted-text">No result images found in GIFT output directory.</p>'
        analyses_html += f"""
    <h2>Multivariate MANCOVA</h2>
    <div class="analysis-block">
      <div class="analysis-title">Global Multivariate</div>
      <p>Multivariate analysis of covariance across all sites, components, and networks.</p>
      {inner}
    </div>"""
    elif r.get("run_mancova"):
        analyses_html += """
    <h2>Multivariate MANCOVA</h2>
    <div class="analysis-block muted">
      <div class="analysis-title">Multivariate MANCOVA</div>
      <p>Configured but no stats files received from sites.</p>
    </div>"""

    if not skip_gica and not r.get("run_mancova") and not r.get("run_univariate_tests"):
        analyses_html += "<p>No statistical analyses were configured to run.</p>"

    # --- Configuration summary ---
    threshdesc = parameters.get("threshdesc", "fdr")
    p_threshold = parameters.get("p_threshold", 0.05)
    num_of_pcs = parameters.get("numOfPCs", [4, 4, 4])
    freq_limits = parameters.get("freq_limits", [0.1, 0.15])
    num_components = parameters.get("num_components", 53)
    template = parameters.get("scica_template") or parameters.get("template", "—")
    tr = parameters.get("TR", "—")

    config_html = f"""
    <h2>Configuration</h2>
    <table>
      <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>Template</td><td>{template}</td></tr>
        <tr><td>ICA Components</td><td>{num_components}</td></tr>
        <tr><td>TR (s)</td><td>{tr}</td></tr>
        <tr><td>Features</td><td>{", ".join(features) if features else "none"}</td></tr>
        <tr><td>Num of PCs</td><td>{num_of_pcs}</td></tr>
        <tr><td>Freq limits (Hz)</td><td>{freq_limits}</td></tr>
        <tr><td>Threshold method</td><td>{threshdesc}</td></tr>
        <tr><td>p-threshold</td><td>{p_threshold}</td></tr>
      </tbody>
    </table>"""

    status_class = "badge-ok" if "completed" in status else "badge-warn"
    body = f"""
    <h1>Federated MANCOVA</h1>
    <p class="subtitle">
      Aggregated results &mdash; <span class="{status_class}">{status}</span>
    </p>
    <hr>
    {cards}
    {site_table}
    {analyses_html}
    {config_html}
    """

    return _wrap(body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def _embed_gift_results(html_path: str, aggregation_dir: str) -> str:
    """Embed GIFT result PNGs as base64 data URIs for a self-contained report."""
    result_dir = os.path.dirname(html_path)

    univariate_pngs = sorted(_glob.glob(os.path.join(result_dir, "univariate_results_*.png")))
    features_pngs = sorted(_glob.glob(os.path.join(result_dir, "features_comp_*.png")))
    known = set(univariate_pngs) | set(features_pngs)
    other_pngs = sorted(p for p in _glob.glob(os.path.join(result_dir, "*.png")) if p not in known)

    html = ""

    if univariate_pngs:
        html += '<div class="gift-section">\n'
        html += '<div class="gift-section-title">Univariate Results</div>\n'
        html += '<p style="font-size:0.85em;color:#666;margin:4px 0 10px 0">Signed -log₁₀(p) heatmaps for FNC and spectra. FNC: component × component. Spectra: component × frequency.</p>\n'
        html += '<div class="gift-grid-univariate">\n'
        for p in univariate_pngs:
            src = _png_data_uri(p)
            html += f'  <img src="{src}" class="gift-img" alt="Univariate results">\n'
        html += '</div>\n</div>\n'

    if other_pngs:
        html += '<div class="gift-section">\n'
        html += '<div class="gift-section-title">MANCOVA Results</div>\n'
        html += '<p style="font-size:0.85em;color:#666;margin:4px 0 10px 0">Multivariate MANCOVA component and FNC results.</p>\n'
        html += '<div class="gift-results-wide">\n'
        for p in other_pngs:
            src = _png_data_uri(p)
            html += f'  <img src="{src}" class="gift-img-wide" alt="{os.path.basename(p)}">\n'
        html += '</div>\n</div>\n'

    if features_pngs:
        html += '<details class="gift-section gift-details">\n'
        html += ('<summary class="gift-section-title">Feature Components '
                 '<span style="font-weight:normal;color:#888;font-size:0.88em">'
                 f'({len(features_pngs)} images — click to expand)'
                 '</span></summary>\n')
        html += '<p style="font-size:0.85em;color:#666;margin:8px 0 10px 0">Spatial T-maps and spectra / FNC correlations per ICA component.</p>\n'
        html += '<div class="gift-grid">\n'
        for p in features_pngs:
            src = _png_data_uri(p)
            html += f'  <img src="{src}" class="gift-img" alt="{os.path.basename(p)}">\n'
        html += '</div>\n</details>\n'

    if not html:
        html = '<p class="muted-text">No result images found in GIFT output directory.</p>'

    return html


def _report_links(paths: List[str], base_dir: str) -> str:
    if not paths:
        return "<p class='muted-text'>No report files found.</p>"
    items = ""
    for p in paths:
        name = os.path.basename(p)
        items += f'<li><span class="muted-text">{name}</span></li>'
    return f"<ul class='report-links'>{items}</ul>"


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------

def _wrap(body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <title>Federated MANCOVA &mdash; Results</title>
    <style>
      *, *::before, *::after {{ box-sizing: border-box; }}
      body {{ font-family: sans-serif; color: #222; margin: 0; padding: 32px 40px;
              background: #f9f9f9; }}
      h1 {{ font-size: 1.6em; margin: 0 0 4px 0; color: #1a1a2e; }}
      p.subtitle {{ margin: 0 0 16px 0; color: #555; font-size: 1em; }}
      h2 {{ font-size: 1.1em; color: #16213e; margin: 32px 0 8px 0; padding-bottom: 4px;
            border-bottom: 2px solid #009879; display: inline-block; }}
      hr {{ border: none; border-top: 1px solid #ddd; margin: 24px 0; }}
      p {{ color: #555; font-size: 0.9em; margin: 0 0 10px 0; line-height: 1.5; }}
      .muted-text {{ color: #aaa; font-style: italic; font-size: 0.85em; }}

      /* Cards */
      .card-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0 28px 0; }}
      .card {{ background: white; border: 1px solid #e0e0e0; border-radius: 8px;
               padding: 16px 20px; min-width: 150px; flex: 1; }}
      .card.accent {{ border-top: 4px solid #009879; }}
      .card-label {{ font-size: 0.78em; color: #888; text-transform: uppercase;
                    letter-spacing: 0.05em; margin-bottom: 6px; }}
      .card-value {{ font-size: 1.6em; font-weight: bold; color: #1a1a2e; line-height: 1.1; }}
      .card-sub {{ font-size: 0.78em; color: #aaa; margin-top: 4px; }}

      /* Tables */
      table {{ border-collapse: collapse; width: 100%; font-size: 0.9em;
               margin: 12px 0 24px 0; background: white; }}
      table thead tr {{ background-color: #009879; color: #ffffff; text-align: left; }}
      table th, table td {{ padding: 11px 15px; white-space: nowrap; }}
      table tbody tr {{ border-bottom: 1px solid #e8e8e8; }}
      table tbody tr:nth-of-type(even) {{ background-color: #f5f5f5; }}
      table td:first-child {{ font-weight: bold; color: #333; }}

      /* Badges */
      .badge-ok   {{ background: #d4edda; color: #155724; padding: 2px 8px;
                     border-radius: 10px; font-size: 0.82em; font-weight: bold; }}
      .badge-warn {{ background: #fff3cd; color: #856404; padding: 2px 8px;
                     border-radius: 10px; font-size: 0.82em; font-weight: bold; }}

      /* Analysis blocks */
      .analysis-block {{ background: white; border: 1px solid #e0e0e0; border-radius: 8px;
                          padding: 16px 20px; margin: 12px 0; }}
      .analysis-block.muted {{ border-left: 4px solid #ddd; opacity: 0.7; }}
      .analysis-block:not(.muted) {{ border-left: 4px solid #009879; }}
      .analysis-title {{ font-weight: bold; color: #1a1a2e; font-size: 1em;
                          margin-bottom: 6px; }}

      /* Report links */
      .report-links {{ margin: 8px 0 0 0; padding-left: 20px; }}
      .report-links li {{ margin: 4px 0; }}
      .report-links a {{ color: #009879; text-decoration: none; font-size: 0.9em; }}
      .report-links a:hover {{ text-decoration: underline; }}

      /* GIFT embedded results */
      .gift-section {{ margin: 16px 0 8px 0; }}
      .gift-section-title {{ font-weight: bold; color: #16213e; font-size: 0.95em;
                              margin-bottom: 4px; cursor: pointer; }}
      .gift-details summary {{ list-style: none; }}
      .gift-details summary::-webkit-details-marker {{ display: none; }}
      .gift-details summary::before {{ content: "▶ "; font-size: 0.8em; color: #009879; }}
      .gift-details[open] summary::before {{ content: "▼ "; }}
      .gift-results-wide {{ margin: 8px 0; }}
      .gift-img-wide {{ max-width: 100%; height: auto; border-radius: 6px;
                        border: 1px solid #e0e0e0; display: block; }}
      .gift-grid-univariate {{ display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
                    gap: 14px; margin: 8px 0; }}
      .gift-grid {{ display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                    gap: 10px; margin: 8px 0; }}
      .gift-grid a {{ display: block; }}
      .gift-img {{ width: 100%; height: auto; border-radius: 4px;
                   border: 1px solid #e0e0e0; display: block;
                   transition: box-shadow 0.15s; }}
      .gift-img:hover {{ box-shadow: 0 2px 10px rgba(0,0,0,0.15); }}
    </style>
  </head>
  <body>{body}</body>
</html>"""
