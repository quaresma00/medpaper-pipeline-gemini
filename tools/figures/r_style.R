# Shared, deterministic R publication graphics. No model fitting or package installation.
medpaper_require <- function(packages) {
  missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing)) stop("Missing R packages: ", paste(missing, collapse = ", "),
                            ". Restore the study's renv environment; do not switch languages silently.")
}

medpaper_theme <- function(base_size = 10, family = "Arial") {
  medpaper_require("ggplot2")
  ggplot2::theme_classic(base_size = base_size, base_family = family) +
    ggplot2::theme(text = ggplot2::element_text(colour = "black"),
                   axis.line = ggplot2::element_line(linewidth = 0.25),
                   axis.ticks = ggplot2::element_line(linewidth = 0.25),
                   plot.subtitle = ggplot2::element_blank(),
                   plot.caption = ggplot2::element_blank(),
                   legend.position = "bottom", legend.title = ggplot2::element_blank(),
                   plot.margin = ggplot2::margin(4, 4, 4, 4, unit = "mm"),
                   plot.background = ggplot2::element_rect(fill = "white", colour = NA))
}

medpaper_palette <- c("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9")

# Optional journal-inspired or custom colours; never restricts comparator-matched palettes.
medpaper_colours <- function(n, palette="okabe_ito") {
  if (length(n)!=1L || !is.finite(n) || n<1 || n!=as.integer(n)) stop("Positive integer colour count required")
  if (is.character(palette) && length(palette) > 1L) {
    if (length(palette) < n || anyNA(palette)) stop("Custom colour vector shorter than group count")
    return(palette[seq_len(n)])
  }
  if (palette=="okabe_ito") {
    if (n > length(medpaper_palette)) stop("Choose an explicit palette for more groups; do not recycle colours")
    return(medpaper_palette[seq_len(n)])
  }
  if (palette %in% c("viridis", "cividis", "plasma", "magma", "hcl_dark3")) {
    hcl_name <- if (palette == "hcl_dark3") "Dark 3" else tools::toTitleCase(palette)
    return(grDevices::hcl.colors(n, palette = hcl_name))
  }
  palettes <- c(nejm="pal_nejm", lancet="pal_lancet", jama="pal_jama", jco="pal_jco")
  if(!palette %in% names(palettes)) stop("Unknown selected palette")
  medpaper_require("ggsci")
  colours <- getExportedValue("ggsci",palettes[[palette]])()(n)
  if(length(colours)!=n || anyNA(colours)) stop("Selected palette does not support this group count")
  colours
}

# Recursively unpack leaf ggplot panels from any native patchwork tree (e.g. (p1 | p2) / p3)
# so comparator-driven native patchwork layouts never require manual panel extraction.
medpaper_extract_panels <- function(obj) {
  if (inherits(obj, "patchwork")) {
    sub_list <- if (is.list(obj$patches$plots)) obj$patches$plots else list()
    current <- obj
    current$patches <- NULL
    class(current) <- setdiff(class(current), "patchwork")
    out <- list()
    for (item in sub_list) out <- c(out, medpaper_extract_panels(item))
    if (inherits(current, "ggplot") && (length(current$layers) > 0L || length(current$data) > 0L || !length(out))) {
      out <- c(out, list(current))
    }
    return(out)
  }
  if (inherits(obj, "ggplot")) return(list(obj))
  list()
}

# Flexible multi-panel composition supporting arbitrary patchwork design matrices, widths, heights, and shared guides.
medpaper_compose <- function(panels, ncol = NULL, nrow = NULL, design = NULL,
                             widths = NULL, heights = NULL, guides = "keep",
                             labels = LETTERS[seq_along(panels)]) {
  medpaper_require(c("ggplot2", "patchwork"))
  if (!is.list(panels) || length(panels) < 2L)
    stop("Supply at least two component ggplot panels.")
  if (!is.null(labels)) {
    if (length(labels) != length(panels) || anyNA(labels) || anyDuplicated(labels) || any(!grepl("^[A-Z]$", labels)))
      stop("Panel labels must be unique uppercase letters (or NULL when unlabelled).")
  }
  if (is.null(ncol) && is.null(nrow) && is.null(design)) ncol <- 1L
  wrapped <- patchwork::wrap_plots(
    panels, ncol = if (is.null(ncol)) NULL else as.integer(ncol),
    nrow = if (is.null(nrow)) NULL else as.integer(nrow),
    design = design, widths = widths, heights = heights, guides = guides
  )
  if (!is.null(labels)) {
    wrapped <- wrapped + patchwork::plot_annotation(tag_levels = list(labels))
  }
  wrapped &
    ggplot2::theme(plot.tag.position = c(0, 1),
                   plot.tag = ggplot2::element_text(size = 10, face = "bold", hjust = 0, vjust = 1, colour = "black"),
                   plot.margin = ggplot2::margin(6, 4, 4, 6, unit = "mm"))
}

# Display strings only: never rename data levels, populations or model objects.
medpaper_label <- function(value) {
  if (!is.character(value)) return(value)
  policy <- jsonlite::fromJSON(Sys.getenv("MEDPAPER_LABEL_POLICY", "{}"))
  if (!is.null(policy$labels)) for (key in names(policy$labels)) value[which(!is.na(value) & value == key)] <- policy$labels[[key]]
  if (!is.null(policy$spelling) && grepl("^american|^en-us$|^us$", policy$spelling, ignore.case = TRUE)) policy$spelling <- "american"
  if (!is.null(policy$spelling) && grepl("^british|^en-gb$|^uk$", policy$spelling, ignore.case = TRUE)) policy$spelling <- "british"
  pairs <- c(colour="color", colours="colors", centre="center", centres="centers", tumour="tumor", randomised="randomized", analysed="analyzed", modelling="modeling")
  if (identical(policy$spelling, "british")) pairs <- stats::setNames(names(pairs), pairs)
  if (!is.null(policy$spelling) && nzchar(policy$spelling)) for (word in names(pairs)) value <- gsub(paste0("\\b", word, "\\b"), pairs[[word]], value)
  value
}

medpaper_number <- function(value) {
  policy <- jsonlite::fromJSON(Sys.getenv("MEDPAPER_LABEL_POLICY", "{}"))
  mark <- if (is.null(policy$number_format$thousands)) "" else policy$number_format$thousands
  if (identical(mark, "thin")) mark <- "\u2009"
  format(value, trim = TRUE, scientific = FALSE, big.mark = mark)
}

medpaper_result <- function(relative_path) {
  medpaper_require("jsonlite")
  allowed <- jsonlite::fromJSON(Sys.getenv("MEDPAPER_SOURCE_RESULTS", "[]"))
  if (!relative_path %in% allowed) stop("Undeclared figure result input: ", relative_path)
  jsonlite::fromJSON(file.path(Sys.getenv("MEDPAPER_PROJECT"), relative_path), simplifyVector = FALSE)
}

medpaper_bar_zero <- function(built, geom_names) {
  groups <- list()
  for (d in built$data[geom_names %in% c("GeomBar", "GeomCol")]) for (i in seq_len(nrow(d))) {
    flip <- "flipped_aes" %in% names(d) && isTRUE(d$flipped_aes[i])
    edge <- sort(if (flip) c(d$xmin[i], d$xmax[i]) else c(d$ymin[i], d$ymax[i]))
    pos <- if (flip) d$y[i] else d$x[i]
    panel <- as.integer(d$PANEL[i])
    limits <- built$layout$panel_params[[panel]][[if (flip) "x.range" else "y.range"]]
    if (length(edge) != 2L || any(!is.finite(edge)) || length(limits) != 2L || min(limits) > 1e-8 || max(limits) < -1e-8) return(FALSE)
    key <- paste(panel, flip, round(pos, 8), sep = ":")
    groups[[key]] <- rbind(groups[[key]], edge)
  }
  for (edges in groups) {
    edges <- matrix(edges, ncol = 2L); edges <- edges[order(edges[, 1]), , drop = FALSE]
    lo <- edges[1, 1]; hi <- edges[1, 2]
    if (nrow(edges) > 1L) for (i in 2:nrow(edges)) {
      if (edges[i, 1] > hi + 1e-8) return(FALSE)
      hi <- max(hi, edges[i, 2])
    }
    if (lo > 1e-8 || hi < -1e-8) return(FALSE)
  }
  TRUE
}

medpaper_layers <- function(plot) {
  # Observe ggplot's built layers, not user-supplied booleans for mandatory elements.
  if (!inherits(plot, "ggplot")) return(NULL)
  built <- ggplot2::ggplot_build(plot)
  geom_names <- vapply(built$plot$layers, function(x) class(x$geom)[1], character(1))
  summary <- lapply(seq_along(geom_names), function(i) {
    d <- built$data[[i]]
    list(geom = geom_names[i], rows = nrow(d),
         xintercept = if ("xintercept" %in% names(d)) unique(d$xintercept) else numeric(),
         slope = if ("slope" %in% names(d)) unique(d$slope) else numeric(),
         intercept = if ("intercept" %in% names(d)) unique(d$intercept) else numeric(),
         ymin = if ("ymin" %in% names(d)) min(d$ymin, na.rm = TRUE) else NULL,
         xmin = if ("xmin" %in% names(d)) min(d$xmin, na.rm = TRUE) else NULL,
         shape = if ("shape" %in% names(d)) unique(d$shape) else numeric(),
         group_sizes = if ("group" %in% names(d)) as.integer(table(d$group)) else integer())
  })
  g <- ggplot2::ggplotGrob(plot)
  legends <- grepl("^guide-box", g$layout$name)
  has_legend <- any(vapply(g$grobs[legends], function(x) !inherits(x, "zeroGrob"), logical(1)))
  label <- function(name) {
    x <- built$plot$labels[[name]]
    if (is.null(x)) "" else paste(as.character(x), collapse = " ")
  }
  ranges <- lapply(built$layout$panel_params, function(x) list(x = x$x.range, y = x$y.range))
  clipped_data <- list()
  bounds_geoms <- c("GeomPoint", "GeomJitter", "GeomErrorbar", "GeomErrorbarh", "GeomLinerange", "GeomPointrange")
  for (i in seq_along(geom_names)) {
    gname <- geom_names[i]
    if (!gname %in% bounds_geoms) next
    d <- built$data[[i]]
    if (!is.data.frame(d) || nrow(d) == 0L) next
    p_idx <- if ("PANEL" %in% names(d)) as.integer(d$PANEL) else rep(1L, nrow(d))
    for (r_i in seq_len(nrow(d))) {
      pid <- p_idx[r_i]
      if (is.na(pid) || pid < 1L || pid > length(built$layout$panel_params)) next
      pp <- built$layout$panel_params[[pid]]
      xr <- pp$x.range; yr <- pp$y.range
      if (is.numeric(xr) && length(xr) == 2L && all(is.finite(xr))) {
        tol_x <- max(1e-6, abs(diff(xr)) * 0.005)
        for (col in intersect(c("x", "xmin", "xmax"), names(d))) {
          val <- d[[col]][r_i]
          if (is.numeric(val) && is.finite(val) && (val < xr[1] - tol_x || val > xr[2] + tol_x)) {
            clipped_data[[length(clipped_data) + 1L]] <- list(geom = gname, panel = pid, axis = "x", field = col, value = val, range = xr)
            break
          }
        }
      }
      if (is.numeric(yr) && length(yr) == 2L && all(is.finite(yr))) {
        tol_y <- max(1e-6, abs(diff(yr)) * 0.005)
        for (col in intersect(c("y", "ymin", "ymax"), names(d))) {
          val <- d[[col]][r_i]
          if (is.numeric(val) && is.finite(val) && (val < yr[1] - tol_y || val > yr[2] + tol_y)) {
            clipped_data[[length(clipped_data) + 1L]] <- list(geom = gname, panel = pid, axis = "y", field = col, value = val, range = yr)
            break
          }
        }
      }
    }
  }

  orphan_legend <- character()
  if (has_legend) {
    legend_aes <- c("colour", "color", "fill", "shape", "linetype")
    for (sc in built$plot$scales$scales) {
      if (!sc$is_discrete()) next
      matched_aes <- intersect(sc$aesthetics, legend_aes)
      if (!length(matched_aes)) next
      if (!is.null(sc$guide) && identical(sc$guide, "none")) next
      lims <- tryCatch(sc$get_limits(), error = function(e) NULL)
      if (!length(lims)) next
      lbls <- tryCatch(as.character(sc$get_labels(lims)), error = function(e) as.character(lims))
      mapped <- tryCatch(sc$map(lims), error = function(e) NULL)
      if (is.null(mapped) || length(mapped) != length(lims)) next
      aes_col <- if ("colour" %in% matched_aes || "color" %in% matched_aes) "colour" else matched_aes[1]
      seen_cols <- character()
      col_present_in_layers <- FALSE
      for (k in seq_along(built$data)) {
        dk <- built$data[[k]]
        if (!is.data.frame(dk) || nrow(dk) == 0L) next
        if (aes_col %in% names(dk)) {
          col_present_in_layers <- TRUE
          vals <- dk[[aes_col]]
          vals <- vals[!is.na(vals)]
          if (length(vals)) seen_cols <- union(seen_cols, as.character(vals))
        }
      }
      if (col_present_in_layers && length(seen_cols)) {
        for (idx in seq_along(lims)) {
          mv <- as.character(mapped[idx])
          if (!is.na(mv) && nzchar(mv) && !(mv %in% seen_cols)) {
            lbl <- if (idx <= length(lbls) && !is.na(lbls[idx])) lbls[idx] else as.character(lims[idx])
            if (nzchar(lbl)) orphan_legend <- union(orphan_legend, lbl)
          }
        }
      }
    }
  }

  list(layers = summary, bar_baseline_zero = medpaper_bar_zero(built, geom_names),
       title = label("title"), subtitle = label("subtitle"), caption = label("caption"),
       x_label = label("x"), y_label = label("y"),
       legend = has_legend, ranges = ranges,
       clipped_data = clipped_data, orphan_legend = orphan_legend)
}

medpaper_save <- function(plot, stem, width = "single", height_mm = 75, dpi = 600,
                         panels = NULL, tiff = FALSE) {
  medpaper_require(c("ggplot2", "jsonlite", "ragg", "svglite", "systemfonts"))
  if (is.list(plot) && !inherits(plot, c("ggplot", "grob", "gTree", "gtable")) && !is.null(plot$plot)) {
    if (is.null(panels) && is.list(plot$panels)) panels <- plot$panels
    plot <- plot$plot
  }
  if (is.null(panels)) {
    panels <- if (inherits(plot, "patchwork")) medpaper_extract_panels(plot) else list(plot)
  } else if (inherits(plot, "patchwork") && length(panels) == 1L && identical(panels[[1]], plot)) {
    panels <- medpaper_extract_panels(plot)
  }
  has_nonempty <- function(x) is.character(x) && length(x) > 0L && any(nzchar(trimws(x)))
  check_no_subtitle_or_caption <- function(item) {
    if (inherits(item, "ggplot")) {
      if (has_nonempty(item$labels$subtitle) || has_nonempty(item$labels$caption))
        stop("Figure subtitle and plot caption are forbidden in medical figures; move all explanatory text to 05_figures/legends.md.")
      if (!is.null(item$patches$annotation) && (has_nonempty(item$patches$annotation$subtitle) || has_nonempty(item$patches$annotation$caption)))
        stop("Patchwork subtitle and caption are forbidden in medical figures; move all explanatory text to 05_figures/legends.md.")
    }
  }
  check_no_subtitle_or_caption(plot)
  for (p_item in panels) check_no_subtitle_or_caption(p_item)
  apply_labels <- function(item) {
    if (inherits(item, "ggplot")) {
      for (name in c("title", "subtitle", "caption", "x", "y", "colour", "color", "fill", "shape", "linetype", "size", "alpha")) {
        if (is.character(item$labels[[name]])) item$labels[[name]] <- medpaper_label(item$labels[[name]])
      }
      for (scale in item$scales$scales) {
        if (scale$is_discrete() && inherits(scale$labels, "waiver")) scale$labels <- medpaper_label
      }
    }
    policy <- jsonlite::fromJSON(Sys.getenv("MEDPAPER_LABEL_POLICY", "{}"))
    if (inherits(item, "ggplot") && length(policy$number_format)) for (scale in item$scales$scales) if (!scale$is_discrete() && inherits(scale$labels, "waiver")) scale$labels <- medpaper_number
    item
  }
  plot <- apply_labels(plot); panels <- lapply(panels, apply_labels)
  output <- Sys.getenv("MEDPAPER_RENDER_STEM")
  if (!nzchar(output)) stop("Use tools/figures/render_r.py; a managed staging directory is required.")
  if (basename(stem) != basename(output)) stop("Figure script stem differs from the requested plan entry.")
  widths <- c(single = 90, `1.5` = 140, double = 180)
  policy <- jsonlite::fromJSON(Sys.getenv("MEDPAPER_LABEL_POLICY", "{}"))
  if (!is.null(policy$column_width_mm_single)) widths["single"] <- policy$column_width_mm_single
  if (!is.null(policy$column_width_mm_double)) widths["double"] <- policy$column_width_mm_double
  if (!width %in% names(widths) || !is.finite(height_mm) || height_mm <= 0 || dpi < 300)
    stop("Invalid publication dimensions/resolution")
  if (!inherits(plot, c("ggplot", "grob", "gTree", "gtable")))
    stop("Plot must be a ggplot/patchwork or grid grob; use the dedicated R package's grid/ggplot export.")
  if (inherits(plot, "patchwork") && length(panels) == 1L)
    stop("For patchwork give panels=list(actual_component_ggplots) for structural inspection.")
  dir.create(dirname(output), recursive = TRUE, showWarnings = FALSE)
  # Grid measures font metrics on the active device. Opening the same system-font SVG
  # device first prevents a default PostScript device from rejecting installed Arial.
  svglite::svglite(paste0(output, ".svg"), width = unname(widths[width]) / 25.4,
                   height = height_mm / 25.4, bg = "white")
  svg_device <- grDevices::dev.cur()
  on.exit(if (grDevices::dev.cur() == svg_device) grDevices::dev.off(), add = TRUE)
  metadata <- list(schema_version = 1L, engine = "R", width_class = width,
                   size_mm = c(unname(widths[width]), height_mm), dpi = dpi,
                   panels = Filter(Negate(is.null), lapply(panels, medpaper_layers)),
                   r_version = R.version.string,
                   packages = setNames(lapply(c("ggplot2", "jsonlite", "ragg", "svglite", "systemfonts"),
                         function(p) as.character(utils::packageVersion(p))),
                         c("ggplot2", "jsonlite", "ragg", "svglite", "systemfonts")))
  if (inherits(plot, "ggplot")) print(plot) else {
    grid::grid.newpage()
    grid::grid.draw(plot)
  }
  grDevices::dev.off()
  # Explicit objects and physical sizes avoid last-plot/device-size surprises.
  ggplot2::ggsave(paste0(output, ".pdf"), plot = plot, device = grDevices::cairo_pdf,
                 width = unname(widths[width]), height = height_mm, units = "mm", bg = "white")
  ggplot2::ggsave(paste0(output, ".png"), plot = plot, device = ragg::agg_png,
                 width = unname(widths[width]), height = height_mm, units = "mm", dpi = dpi, bg = "white")
  if (tiff) ggplot2::ggsave(paste0(output, ".tiff"), plot = plot, device = ragg::agg_tiff,
                 width = unname(widths[width]), height = height_mm, units = "mm", dpi = dpi,
                 compression = "lzw", bg = "white")
  jsonlite::write_json(metadata, paste0(output, ".rmeta.json"), auto_unbox = TRUE,
                       pretty = TRUE, null = "null", na = "null")
  invisible(metadata)
}
