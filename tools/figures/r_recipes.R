# Small graph recipes consuming approved, full-precision results. Never fit a model here.
medpaper_check_numeric <- function(data, columns) {
  if (!is.data.frame(data) || !nrow(data) || !all(columns %in% names(data))) stop("Missing complete plotting data")
  for (column in columns) if (!is.numeric(data[[column]]) || any(!is.finite(data[[column]])))
    stop("Non-numeric/missing plotting input: ",column,"; resolve at the analysis owner, never silently drop rows")
}

medpaper_forest <- function(data, measure="Adjusted odds ratio", null=1, log_scale=TRUE) {
  medpaper_require("ggplot2")
  medpaper_check_numeric(data,c("estimate","lower","upper"))
  if (!"label" %in% names(data) || anyDuplicated(data$label) || any(!nzchar(data$label))) stop("Unique clinical row labels required")
  if (any(data$lower>data$estimate | data$estimate>data$upper)) stop("Invalid confidence interval")
  if (log_scale && (any(data$lower<=0) || null<=0)) stop("Logarithmic effect measures must be positive")
  data$label <- medpaper_label(data$label)
  data$label <- factor(data$label,levels=rev(data$label))
  p <- ggplot2::ggplot(data,ggplot2::aes(x=estimate,y=label)) +
    ggplot2::geom_vline(xintercept=null,linetype="dashed",linewidth=.3) +
    ggplot2::geom_errorbar(ggplot2::aes(xmin=lower,xmax=upper),orientation="y",width=.15,linewidth=.35) +
    ggplot2::geom_point(size=2) + ggplot2::labs(x=paste0(measure," (95% CI)"),y=NULL) + medpaper_theme()
  if(log_scale) p <- p + ggplot2::scale_x_log10()
  # Exact effect/CI values can be printed by a study-specific aligned statistics column.
  # This intentionally does not guess the right-hand layout or clinical wording.
  p
}

# One measured ggplot: exact source estimates beside their intervals, not a new
# model or multiple pseudo-panels. Explicit measure/null/scale prevent guessing
# an OR/HR/RR/linear coefficient from a generic result field called estimate.
medpaper_forest_table <- function(data, measure, null, log_scale, digits=2L,
                                  interval_label="95% CI", effect_header=NULL) {
  if (missing(measure) || missing(null) || missing(log_scale) ||
      length(measure)!=1L || is.na(measure) || !nzchar(measure) ||
      length(null)!=1L || !is.finite(null) || !is.logical(log_scale) || length(log_scale)!=1L || is.na(log_scale))
    stop("Explicit source-supported measure, null value and logical scale are required")
  if(length(digits)!=1L || !is.numeric(digits) || !is.finite(digits) || digits<0L || digits>8L || digits!=as.integer(digits))
    stop("Use explicit display precision from 0 to 8 digits")
  if(length(interval_label)!=1L || is.na(interval_label) || !nzchar(interval_label)) stop("Declare the actual interval label")
  p <- medpaper_forest(data,measure=measure,null=null,log_scale=log_scale)
  format_effect <- function(x) ifelse(x!=0 & round(x,digits)==0,
                                      formatC(x,format="g",digits=2),formatC(x,format="f",digits=digits))
  data$label <- medpaper_label(data$label)
  data$label <- factor(data$label,levels=rev(data$label))
  data$effect_text <- paste0(format_effect(data$estimate)," (",format_effect(data$lower)," to ",format_effect(data$upper),")")
  if(is.null(effect_header)) effect_header <- paste0(measure,"\n(",interval_label,")")
  p + ggplot2::geom_text(data=data,ggplot2::aes(x=Inf,y=label,label=effect_text),
                         inherit.aes=FALSE,hjust=-.08,size=9/ggplot2::.pt) +
    ggplot2::annotate("label",x=Inf,y=Inf,label=effect_header,hjust=-.08,vjust=-.15,
                       size=9/ggplot2::.pt,fontface="bold",fill="white",colour="black",
                       linewidth=0,label.padding=grid::unit(0.15,"lines")) +
    ggplot2::coord_cartesian(clip="off") + ggplot2::labs(x=measure,y=NULL) +
    ggplot2::theme(plot.margin=ggplot2::margin(12,48,4,4,unit="mm"))
}

# Multi-column publication forest layout using independent aligned patchwork panels:
# avoids fragile x=Inf coordinates, supports duplicate subgroup level labels (Yes/No),
# Reference / NE rows, optional left count columns, and optional P for interaction column.
# Returns list(plot = <patchwork>, panels = list(p_left, p_forest, p_right)).
medpaper_forest_panels <- function(data, measure, null=1, log_scale=TRUE, digits=2L,
                                   interval_label="95% CI", label_header="Characteristic",
                                   left_cols=NULL, left_headers=NULL,
                                   effect_header=NULL, p_col=NULL, p_header="P value",
                                   p_interaction_col=NULL, p_interaction_header="P for interaction",
                                   xlim=NULL, col_widths=NULL) {
  medpaper_require(c("ggplot2", "patchwork", "grid"))
  has_left_extra <- !is.null(left_cols) && length(left_cols) > 0L && all(left_cols %in% names(data))
  has_p <- !is.null(p_col) && p_col %in% names(data)
  has_pint <- !is.null(p_interaction_col) && p_interaction_col %in% names(data)
  if (is.null(col_widths)) {
    w_left <- if (has_left_extra) 1.75 + 0.35 * (length(left_cols) - 1L) else 1.30
    w_right <- 1.05 + (if (has_p) 0.35 else 0.0) + (if (has_pint) 0.45 else 0.0)
    col_widths <- c(w_left, 1.35, w_right)
  }
  if (!is.data.frame(data) || !nrow(data) || !"label" %in% names(data))
    stop("data.frame with 'label' required")
  if (missing(measure) || missing(null) || missing(log_scale) ||
      length(measure)!=1L || is.na(measure) || !nzchar(measure) ||
      length(null)!=1L || !is.finite(null) || !is.logical(log_scale) || length(log_scale)!=1L)
    stop("Explicit measure, null, and logical log_scale required")
  data$label <- medpaper_label(as.character(data$label))
  n_rows <- nrow(data)
  data$y_pos <- rev(seq_len(n_rows))
  is_grp <- if ("is_group" %in% names(data)) isTRUE_vec(data$is_group) else rep(FALSE, n_rows)
  is_ind <- if ("indent" %in% names(data)) isTRUE_vec(data$indent) else rep(FALSE, n_rows)
  row_status <- if ("status" %in% names(data)) trimws(as.character(data$status)) else rep("", n_rows)
  row_status[is.na(row_status)] <- ""
  is_ref <- grepl("^(?:ref|reference|1\\s*\\[reference\\])$", row_status, ignore.case=TRUE)
  is_ne <- grepl("^(?:ne|not\\s+estimable|na|nr)$", row_status, ignore.case=TRUE)

  format_effect <- function(x) ifelse(!is.finite(x), "", ifelse(x!=0 & round(x,digits)==0,
                                      formatC(x,format="g",digits=2),formatC(x,format="f",digits=digits)))
  has_est <- all(c("estimate","lower","upper") %in% names(data))
  plot_rows <- if (has_est) (is.finite(data$estimate) & is.finite(data$lower) & is.finite(data$upper) & !is_grp & !is_ref & !is_ne) else rep(FALSE, n_rows)
  if (any(plot_rows)) {
    sub_df <- data[plot_rows, , drop=FALSE]
    if (any(sub_df$lower > sub_df$estimate | sub_df$estimate > sub_df$upper)) stop("Invalid confidence interval")
    if (log_scale && (any(sub_df$lower <= 0) || null <= 0)) stop("Logarithmic effect measures must be positive")
  }

  y_lims <- c(0.70, n_rows + 0.92)
  y_header <- n_rows + 0.78

  # Left column: structured labels + optional count/rate columns
  data$label_x <- ifelse(is_ind, if (has_left_extra) 0.04 else 0.08, 0.0)
  data$label_face <- ifelse(is_grp, "bold", "plain")
  p_left <- ggplot2::ggplot(data) +
    ggplot2::geom_text(ggplot2::aes(x=label_x, y=y_pos, label=label, fontface=label_face),
                       hjust=0, size=8.5/ggplot2::.pt, colour="black") +
    ggplot2::annotate("text", x=0.0, y=y_header, label=medpaper_label(label_header),
                      hjust=0, fontface="bold", size=8.8/ggplot2::.pt, colour="black")
  if (has_left_extra) {
    n_lc <- length(left_cols)
    if (is.null(left_headers)) left_headers <- left_cols
    x_positions <- if (n_lc == 1L) 0.62 else seq(0.50, 0.80, length.out=n_lc)
    for (k in seq_len(n_lc)) {
      col_vals <- as.character(data[[left_cols[k]]])
      col_vals[is.na(col_vals)] <- ""
      col_df <- data.frame(x_pos=rep(x_positions[k], n_rows), y_pos=data$y_pos, val=col_vals)
      p_left <- p_left +
        ggplot2::geom_text(data=col_df, ggplot2::aes(x=x_pos, y=y_pos, label=val),
                           inherit.aes=FALSE, hjust=0, size=8.2/ggplot2::.pt, colour="black") +
        ggplot2::annotate("text", x=x_positions[k], y=y_header, label=medpaper_label(left_headers[k]),
                          hjust=0, fontface="bold", size=8.5/ggplot2::.pt, colour="black")
    }
  }
  p_left <- p_left +
    ggplot2::geom_hline(yintercept=n_rows + 0.45, linewidth=0.35, colour="black") +
    ggplot2::scale_x_continuous(limits=c(0, 1), expand=c(0, 0)) +
    ggplot2::scale_y_continuous(limits=y_lims, expand=c(0, 0)) +
    ggplot2::labs(x=NULL, y=NULL) +
    ggplot2::theme_void() +
    ggplot2::theme(plot.margin=ggplot2::margin(1, 2, 2.5, 1.5, unit="mm"))

  # Middle column: forest plot strictly bounded within axis limits, optional overflow arrows
  fp <- data[plot_rows, , drop=FALSE]
  ref_df <- data[is_ref & !is_grp, , drop=FALSE]
  if (is.null(xlim)) {
    lo_min <- if (nrow(fp)) min(fp$lower, null, na.rm=TRUE) else if (log_scale) null * 0.5 else null - 1
    hi_max <- if (nrow(fp)) max(fp$upper, null, na.rm=TRUE) else if (log_scale) null * 2.0 else null + 1
    xlim <- if (log_scale) c(lo_min * 0.85, hi_max * 1.15) else { span <- max(1e-6, hi_max - lo_min); c(lo_min - 0.08*span, hi_max + 0.08*span) }
  }
  if (nrow(fp)) {
    fp$draw_lower <- pmax(fp$lower, xlim[1])
    fp$draw_upper <- pmin(fp$upper, xlim[2])
    fp$clip_lo <- fp$lower < xlim[1]
    fp$clip_hi <- fp$upper > xlim[2]
    fp$in_bounds <- fp$estimate >= xlim[1] & fp$estimate <= xlim[2]
  }

  p_forest <- ggplot2::ggplot(fp, ggplot2::aes(y=y_pos)) +
    ggplot2::annotate("segment", x=null, xend=null, y=0.72, yend=n_rows + 0.40,
                      linetype="dashed", linewidth=0.35, colour="grey35") +
    ggplot2::geom_vline(xintercept=null, linetype="blank")
  if (nrow(fp)) {
    p_forest <- p_forest +
      ggplot2::geom_errorbar(ggplot2::aes(xmin=draw_lower, xmax=draw_upper), orientation="y",
                             width=0.16, linewidth=0.4, colour="black") +
      ggplot2::geom_point(data=fp[fp$in_bounds, , drop=FALSE], ggplot2::aes(x=estimate, y=y_pos), size=2.1, colour="black")
    if (any(fp$clip_lo)) {
      p_forest <- p_forest + ggplot2::geom_segment(
        data=fp[fp$clip_lo, , drop=FALSE],
        ggplot2::aes(x=draw_upper, xend=xlim[1], y=y_pos, yend=y_pos),
        arrow=grid::arrow(length=grid::unit(1.6, "mm"), type="closed"), linewidth=0.4, colour="black")
    }
    if (any(fp$clip_hi)) {
      p_forest <- p_forest + ggplot2::geom_segment(
        data=fp[fp$clip_hi, , drop=FALSE],
        ggplot2::aes(x=draw_lower, xend=xlim[2], y=y_pos, yend=y_pos),
        arrow=grid::arrow(length=grid::unit(1.6, "mm"), type="closed"), linewidth=0.4, colour="black")
    }
  }
  if (nrow(ref_df) && null >= xlim[1] && null <= xlim[2]) {
    ref_df$ref_x <- null
    p_forest <- p_forest +
      ggplot2::geom_point(data=ref_df, ggplot2::aes(x=ref_x, y=y_pos), inherit.aes=FALSE,
                          shape=15, size=1.8, colour="grey30")
  }
  if (log_scale) {
    p_forest <- p_forest + ggplot2::scale_x_log10()
  }
  p_forest <- p_forest +
    ggplot2::coord_cartesian(xlim=xlim) +
    ggplot2::scale_y_continuous(limits=y_lims, expand=c(0, 0)) +
    ggplot2::labs(x=paste0(measure, " (", interval_label, ")"), y=medpaper_label(label_header)) +
    medpaper_theme() +
    ggplot2::theme(axis.line.y=ggplot2::element_blank(), axis.ticks.y=ggplot2::element_blank(),
                   axis.text.y=ggplot2::element_blank(), axis.title.y=ggplot2::element_blank(),
                   plot.margin=ggplot2::margin(1, 2.5, 1, 2.5, unit="mm"))

  # Right column: aligned effect + CI (+ optional P value + optional P for interaction)
  if (is.null(effect_header)) effect_header <- paste0(measure, " (", interval_label, ")")
  ref_label <- paste0(format(null, trim=TRUE), " [Reference]")
  data$eff_str <- ifelse(
    plot_rows,
    paste0(format_effect(data$estimate), " (", format_effect(data$lower), " to ", format_effect(data$upper), ")"),
    ifelse(is_ref & !is_grp, ref_label, ifelse(is_ne & !is_grp, "NE", ifelse(nzchar(row_status) & !is_grp, row_status, "")))
  )
  data$p_str <- if (has_p) ifelse(is.na(data[[p_col]]), "", as.character(data[[p_col]])) else ""
  data$pint_str <- if (has_pint) ifelse(is.na(data[[p_interaction_col]]), "", as.character(data[[p_interaction_col]])) else ""

  x_eff <- 0.02
  x_p <- if (has_p && has_pint) 0.54 else 0.70
  x_pint <- if (has_p && has_pint) 0.75 else 0.66
  p_right <- ggplot2::ggplot(data) +
    ggplot2::geom_text(ggplot2::aes(x=x_eff, y=y_pos, label=eff_str),
                       hjust=0, size=8.2/ggplot2::.pt, colour="black") +
    ggplot2::annotate("text", x=x_eff, y=y_header, label=effect_header,
                      hjust=0, fontface="bold", size=8.5/ggplot2::.pt, colour="black")
  if (has_p) {
    p_right <- p_right +
      ggplot2::geom_text(ggplot2::aes(x=x_p, y=y_pos, label=p_str),
                         hjust=0, size=8.2/ggplot2::.pt, colour="black") +
      ggplot2::annotate("text", x=x_p, y=y_header, label=p_header,
                        hjust=0, fontface="bold", size=8.5/ggplot2::.pt, colour="black")
  }
  if (has_pint) {
    p_right <- p_right +
      ggplot2::geom_text(ggplot2::aes(x=x_pint, y=y_pos, label=pint_str),
                         hjust=0, size=8.2/ggplot2::.pt, colour="black") +
      ggplot2::annotate("text", x=x_pint, y=y_header, label=p_interaction_header,
                        hjust=0, fontface="bold", size=8.5/ggplot2::.pt, colour="black")
  }
  p_right <- p_right +
    ggplot2::geom_hline(yintercept=n_rows + 0.45, linewidth=0.35, colour="black") +
    ggplot2::scale_x_continuous(limits=c(0, 1), expand=c(0, 0)) +
    ggplot2::scale_y_continuous(limits=y_lims, expand=c(0, 0)) +
    ggplot2::labs(x=NULL, y=NULL) +
    ggplot2::theme_void() +
    ggplot2::theme(plot.margin=ggplot2::margin(1, 2, 2.5, 1.5, unit="mm"))

  composed <- patchwork::wrap_plots(p_left, p_forest, p_right, ncol=3L, widths=col_widths)
  list(plot=composed, panels=list(p_left, p_forest, p_right))
}

medpaper_clinical_forest <- medpaper_forest_panels

isTRUE_vec <- function(x) vapply(x, isTRUE, logical(1))

medpaper_roc <- function(data, legend_title=NULL) {
  medpaper_require("ggplot2")
  medpaper_check_numeric(data,c("fpr","tpr"))
  if (!"group" %in% names(data) || any(data$fpr<0 | data$fpr>1 | data$tpr<0 | data$tpr>1)) stop("Invalid approved ROC coordinates/groups")
  data$group <- medpaper_label(data$group)
  if (!is.null(legend_title)) legend_title <- medpaper_label(legend_title)
  ggplot2::ggplot(data,ggplot2::aes(x=fpr,y=tpr,colour=group,group=group)) +
    ggplot2::geom_abline(slope=1,intercept=0,linetype="dashed",linewidth=.3,colour="grey50") +
    ggplot2::geom_path(linewidth=.5) + ggplot2::coord_equal(xlim=c(0,1),ylim=c(0,1)) +
    ggplot2::labs(x="1 - Specificity",y="Sensitivity",colour=legend_title) + medpaper_theme()
}

medpaper_calibration <- function(data, probability_label="Outcome probability",
                                 ci_band=FALSE, metric_label=NULL,
                                 distribution_data=NULL, dist_bins=30L, dist_height=0.26) {
  medpaper_require("ggplot2")
  medpaper_check_numeric(data,c("predicted","observed"))
  if (!"group" %in% names(data) || any(data$predicted<0 | data$predicted>1 | data$observed<0 | data$observed>1)) stop("Invalid approved calibration coordinates/groups")
  data$group <- medpaper_label(data$group)
  probability_label <- medpaper_label(probability_label)
  p_cal <- ggplot2::ggplot(data,ggplot2::aes(x=predicted,y=observed,colour=group,group=group)) +
    ggplot2::geom_abline(slope=1,intercept=0,linetype="dashed",linewidth=.3,colour="grey50")
  if (isTRUE(ci_band) && all(c("lower", "upper") %in% names(data))) {
    medpaper_check_numeric(data, c("lower", "upper"))
    p_cal <- p_cal + ggplot2::geom_ribbon(
      ggplot2::aes(ymin=lower, ymax=upper, fill=group), alpha=0.14, colour=NA, show.legend=FALSE)
  }
  p_cal <- p_cal +
    ggplot2::geom_line(linewidth=.5) + ggplot2::geom_point(size=1.5) +
    ggplot2::coord_equal(xlim=c(0,1),ylim=c(0,1)) +
    ggplot2::labs(x=paste("Predicted",tolower(probability_label)),y=paste("Observed",tolower(probability_label))) + medpaper_theme()
  if (!is.null(metric_label) && nzchar(trimws(metric_label))) {
    p_cal <- p_cal + ggplot2::annotate(
      "text", x=0.03, y=0.94, label=trimws(metric_label),
      hjust=0, vjust=1, size=8.3/ggplot2::.pt, colour="black")
  }
  if (is.null(distribution_data)) return(p_cal)

  medpaper_require("patchwork")
  medpaper_check_numeric(distribution_data, "predicted")
  if (any(distribution_data$predicted < 0 | distribution_data$predicted > 1))
    stop("Calibration distribution predicted probabilities must lie in [0, 1]")
  p_cal_top <- p_cal +
    ggplot2::coord_cartesian(xlim=c(0, 1), ylim=c(0, 1)) +
    ggplot2::labs(x=NULL) +
    ggplot2::theme(axis.text.x=ggplot2::element_blank(),
                   axis.ticks.x=ggplot2::element_blank(),
                   plot.margin=ggplot2::margin(2, 4, 1, 4, unit="mm"))
  p_dist <- ggplot2::ggplot(distribution_data, ggplot2::aes(x=predicted)) +
    ggplot2::geom_histogram(bins=as.integer(dist_bins), fill="grey75", colour="grey30", linewidth=0.25) +
    ggplot2::coord_cartesian(xlim=c(0, 1)) +
    ggplot2::labs(x=paste("Predicted", tolower(probability_label)), y="Count") +
    medpaper_theme() +
    ggplot2::theme(plot.margin=ggplot2::margin(0.5, 4, 2.5, 4, unit="mm"))
  composed <- patchwork::wrap_plots(p_cal_top, p_dist, ncol=1L, heights=c(1, dist_height))
  list(plot=composed, panels=list(p_cal_top, p_dist))
}

medpaper_calibration_composite <- medpaper_calibration

# Neutral selection diagram for cohorts/records (supports single or multi-source roots,
# multi-reason exclusion detail lists, and optional orthogonal CONSORT/STROBE connectors).
# Counts are supplied individually from executed result exports.
medpaper_selection_flow <- function(nodes, edges, box_width=.36, box_height=.16,
                                    orthogonal=FALSE, family="Arial") {
  medpaper_require("ggplot2")
  medpaper_check_numeric(nodes,c("n","x","y"))
  if(!all(c("id","label") %in% names(nodes)) || anyNA(nodes$id) || anyNA(nodes$label) ||
     any(!nzchar(nodes$id)) || any(!nzchar(nodes$label)) || anyDuplicated(nodes$id) ||
     any(nodes$n<0 | nodes$n!=floor(nodes$n))) stop("Distinct nodes, clinical labels and nonnegative whole counts required")
  if(!is.data.frame(edges) || !nrow(edges) || !all(c("from","to") %in% names(edges)) ||
     anyNA(edges$from) || anyNA(edges$to) || any(!edges$from %in% nodes$id) ||
     any(!edges$to %in% nodes$id) || any(edges$from==edges$to) || anyDuplicated(edges)) stop("Declare actual connected source/destination nodes")
  if(length(box_width)!=1L || length(box_height)!=1L || !is.finite(box_width) || !is.finite(box_height) ||
     box_width<=0 || box_height<=0) stop("Positive box dimensions required")
  nodes$label <- medpaper_label(as.character(nodes$label))
  # Fail on cycles/unconnected nodes; allow >=1 source roots for multi-database / multi-cohort merges.
  unseen <- nodes$id; roots <- setdiff(nodes$id,edges$to)
  if(length(roots)<1L || any(!nodes$id %in% c(edges$from,edges$to))) stop("At least one source root is required and every node must be connected")
  pending <- roots
  while(length(pending)) {
    unseen <- setdiff(unseen,pending)
    pending <- unseen[!vapply(unseen,function(id) any(edges$from[edges$to==id] %in% unseen),logical(1))]
  }
  if(length(unseen)) stop("Selection edges contain a cycle")

  has_detail <- "detail" %in% names(nodes)
  detail_vec <- if (has_detail) ifelse(is.na(nodes$detail), "", trimws(as.character(nodes$detail))) else rep("", nrow(nodes))
  bw_vec <- if ("width" %in% names(nodes) && is.numeric(nodes$width)) nodes$width else rep(box_width, nrow(nodes))
  bh_vec <- if ("height" %in% names(nodes) && is.numeric(nodes$height)) nodes$height else ifelse(nzchar(detail_vec), box_height * 1.55, box_height)

  if(nrow(nodes)>1L) for(i in seq_len(nrow(nodes)-1L)) for(j in (i+1L):nrow(nodes))
    if(abs(nodes$x[i]-nodes$x[j])<(bw_vec[i]+bw_vec[j])/2 && abs(nodes$y[i]-nodes$y[j])<(bh_vec[i]+bh_vec[j])/2)
      stop("Flow boxes overlap; change layout coordinates, not counts")

  texts <- character(nrow(nodes))
  for (i in seq_len(nrow(nodes))) {
    w_lines <- strwrap(nodes$label[i], width=31)
    if (!nzchar(detail_vec[i]) && length(w_lines) > 3L)
      stop("Long flow labels need a larger measured layout or concise clinical wording")
    head_txt <- paste0(paste(w_lines, collapse="\n"), " (n = ", format(nodes$n[i], scientific=FALSE, trim=TRUE), ")")
    if (!nzchar(detail_vec[i])) {
      head_txt <- paste0(paste(w_lines, collapse="\n"), "\nn = ", format(nodes$n[i], scientific=FALSE, trim=TRUE))
      texts[i] <- head_txt
    } else {
      det_lines <- unlist(lapply(strsplit(detail_vec[i], "\n", fixed=TRUE)[[1]], function(s) strwrap(s, width=34)))
      if (length(w_lines) + length(det_lines) > 10L)
        stop("Exclusion detail box exceeds 10 lines; summarize concise clinical categories")
      texts[i] <- paste0(head_txt, "\n", paste(det_lines, collapse="\n"))
    }
  }
  nodes$text <- texts
  nodes$bw <- bw_vec
  nodes$bh <- bh_vec

  a <- nodes[match(edges$from,nodes$id),]; b <- nodes[match(edges$to,nodes$id),]
  plain_segs <- list()
  arrow_segs <- list()
  for (k in seq_len(nrow(edges))) {
    ax <- a$x[k]; ay <- a$y[k]; aw <- a$bw[k]; ah <- a$bh[k]
    bx <- b$x[k]; by <- b$y[k]; bw <- b$bw[k]; bh <- b$bh[k]
    if (isTRUE(orthogonal) && abs(bx - ax) > 1e-6 && abs(by - ay) > 1e-6) {
      # Orthogonal routing: vertical trunk then horizontal branch into side box (or vice versa)
      if (abs(bx - ax) >= aw / 2 + bw / 2) {
        # Side exclusion branch from vertical stem at y = by
        sx_stem <- ax
        sy_stem <- ay - sign(ay - by) * ah / 2
        ex_box <- bx - sign(bx - ax) * bw / 2
        if (abs(by - sy_stem) > 1e-6) {
          plain_segs[[length(plain_segs) + 1L]] <- data.frame(x=sx_stem, y=sy_stem, xend=sx_stem, yend=by)
        }
        arrow_segs[[length(arrow_segs) + 1L]] <- data.frame(x=sx_stem, y=by, xend=ex_box, yend=by)
      } else {
        mid_y <- (ay + by) / 2
        sy_a <- ay + sign(by - ay) * ah / 2
        ey_b <- by - sign(by - ay) * bh / 2
        plain_segs[[length(plain_segs) + 1L]] <- data.frame(x=ax, y=sy_a, xend=ax, yend=mid_y)
        plain_segs[[length(plain_segs) + 1L]] <- data.frame(x=ax, y=mid_y, xend=bx, yend=mid_y)
        arrow_segs[[length(arrow_segs) + 1L]] <- data.frame(x=bx, y=mid_y, xend=bx, yend=ey_b)
      }
    } else {
      horiz <- abs(bx - ax) > abs(by - ay)
      sx <- ax + ifelse(horiz, sign(bx - ax) * aw / 2, 0)
      sy <- ay + ifelse(horiz, 0, sign(by - ay) * ah / 2)
      ex <- bx - ifelse(horiz, sign(bx - ax) * bw / 2, 0)
      ey <- by - ifelse(horiz, 0, sign(by - ay) * bh / 2)
      arrow_segs[[length(arrow_segs) + 1L]] <- data.frame(x=sx, y=sy, xend=ex, yend=ey)
    }
  }
  arrow_df <- do.call(rbind, arrow_segs)
  p <- ggplot2::ggplot()
  if (length(plain_segs)) {
    plain_df <- do.call(rbind, plain_segs)
    p <- p + ggplot2::geom_segment(data=plain_df, ggplot2::aes(x=x, y=y, xend=xend, yend=yend), linewidth=.35, colour="black")
  }
  p +
    ggplot2::geom_segment(data=arrow_df,ggplot2::aes(x=x,y=y,xend=xend,yend=yend),linewidth=.35,colour="black",
                          arrow=grid::arrow(length=grid::unit(1.9,"mm"),type="closed")) +
    ggplot2::geom_rect(data=nodes,ggplot2::aes(xmin=x-bw/2,xmax=x+bw/2,
                                            ymin=y-bh/2,ymax=y+bh/2),fill="white",colour="black",linewidth=.35) +
    ggplot2::geom_text(data=nodes,ggplot2::aes(x=x,y=y,label=text),size=8.5/ggplot2::.pt,family=family,lineheight=.95,colour="black") +
    ggplot2::coord_cartesian(xlim=c(min(nodes$x - nodes$bw * 0.62), max(nodes$x + nodes$bw * 0.62)),
                         ylim=c(min(nodes$y - nodes$bh * 0.65), max(nodes$y + nodes$bh * 0.65)),expand=FALSE) +
    ggplot2::theme_void(base_family=family) +
    ggplot2::theme(plot.margin=ggplot2::margin(2.5,2.5,2.5,2.5,unit="mm"),
                   plot.background=ggplot2::element_rect(fill="white",colour=NA))
}

medpaper_consort_flow <- medpaper_selection_flow

# Publication Kaplan-Meier / cumulative-incidence curve + aligned number-at-risk table
# built purely on ggplot2 + patchwork (no fragile survminer dependency).
# Returns list(plot = <patchwork>, panels = list(p_km, p_risk)).
medpaper_km_survival <- function(curve_data, risk_data, censor_data=NULL,
                                 x_label="Follow-up time",
                                 y_label="Event-free survival probability",
                                 breaks=NULL, ylim=c(0, 1), ci_band=FALSE,
                                 p_label=NULL, palette="okabe_ito",
                                 risk_height=0.30) {
  medpaper_require(c("ggplot2", "patchwork", "grid"))
  medpaper_check_numeric(curve_data, c("time", "surv"))
  medpaper_plot_groups(curve_data, "group")
  medpaper_check_numeric(risk_data, c("time", "n_risk"))
  medpaper_plot_groups(risk_data, "group")
  if (any(curve_data$surv < 0 | curve_data$surv > 1.0001) || any(risk_data$n_risk < 0))
    stop("Invalid survival/CIF coordinates or negative at-risk counts")

  curve_data$group <- medpaper_label(as.character(curve_data$group))
  risk_data$group <- medpaper_label(as.character(risk_data$group))
  groups <- unique(curve_data$group)
  curve_data$group <- factor(curve_data$group, levels=groups)
  risk_data$group <- factor(risk_data$group, levels=rev(groups))
  cols <- medpaper_colours(length(groups), palette=palette)
  names(cols) <- groups

  if (is.null(breaks)) breaks <- sort(unique(risk_data$time))
  t_max <- max(c(curve_data$time, breaks), na.rm=TRUE)
  t_min <- min(c(curve_data$time, breaks, 0), na.rm=TRUE)
  x_pad <- max(1e-6, (t_max - t_min) * 0.03)
  x_lims <- c(t_min - x_pad * 0.4, t_max + x_pad)

  p_km <- ggplot2::ggplot(curve_data, ggplot2::aes(x=time, y=surv, colour=group, group=group))
  if (isTRUE(ci_band) && all(c("lower", "upper") %in% names(curve_data))) {
    medpaper_check_numeric(curve_data, c("lower", "upper"))
    p_km <- p_km + ggplot2::geom_ribbon(
      ggplot2::aes(ymin=lower, ymax=upper, fill=group), alpha=0.14, colour=NA, show.legend=FALSE) +
      ggplot2::scale_fill_manual(values=cols)
  }
  p_km <- p_km +
    ggplot2::geom_step(linewidth=0.6) +
    ggplot2::scale_colour_manual(values=cols) +
    ggplot2::scale_x_continuous(breaks=breaks) +
    ggplot2::scale_y_continuous(limits=ylim) +
    ggplot2::coord_cartesian(xlim=x_lims, ylim=ylim) +
    ggplot2::labs(x=medpaper_label(x_label), y=medpaper_label(y_label)) +
    medpaper_theme() +
    ggplot2::theme(legend.position="top",
                   plot.margin=ggplot2::margin(2, 4, 1, 4, unit="mm"))

  if (!is.null(censor_data) && is.data.frame(censor_data) && nrow(censor_data) > 0L) {
    medpaper_check_numeric(censor_data, c("time", "surv"))
    medpaper_plot_groups(censor_data, "group")
    censor_data$group <- factor(medpaper_label(as.character(censor_data$group)), levels=groups)
    p_km <- p_km + ggplot2::geom_point(
      data=censor_data, ggplot2::aes(x=time, y=surv, colour=group),
      shape=3, size=1.7, stroke=0.45, show.legend=FALSE)
  }
  if (!is.null(p_label) && nzchar(trimws(p_label))) {
    p_km <- p_km + ggplot2::annotate(
      "text", x=t_min + (t_max - t_min) * 0.03, y=ylim[1] + diff(ylim) * 0.10,
      label=trimws(p_label), hjust=0, size=8.5/ggplot2::.pt, colour="black")
  }

  risk_data$label_val <- as.character(as.integer(round(risk_data$n_risk)))
  n_g <- length(groups)
  risk_data$y_num <- as.integer(risk_data$group)
  p_risk <- ggplot2::ggplot(risk_data, ggplot2::aes(x=time, y=y_num, label=label_val)) +
    ggplot2::geom_text(size=8.2/ggplot2::.pt, colour="black") +
    ggplot2::annotate("text", x=t_min, y=n_g + 0.72, label="Number at risk",
                      hjust=0, fontface="bold", size=8.6/ggplot2::.pt, colour="black") +
    ggplot2::scale_x_continuous(breaks=breaks) +
    ggplot2::scale_y_continuous(breaks=seq_len(n_g), labels=rev(groups),
                                limits=c(0.55, n_g + 0.95), expand=c(0, 0)) +
    ggplot2::coord_cartesian(xlim=x_lims) +
    ggplot2::labs(x=medpaper_label(x_label), y=NULL) +
    medpaper_theme() +
    ggplot2::theme(axis.line.y=ggplot2::element_blank(),
                   axis.ticks.y=ggplot2::element_blank(),
                   axis.text.y=ggplot2::element_text(colour="black", size=8.3),
                   plot.margin=ggplot2::margin(0.5, 4, 2.5, 4, unit="mm"))

  composed <- patchwork::wrap_plots(p_km, p_risk, ncol=1L, heights=c(1, risk_height))
  list(plot=composed, panels=list(p_km, p_risk))
}

medpaper_plot_groups <- function(data, fields) {
  if(!all(fields %in% names(data)) || anyNA(data[fields]) ||
     any(!vapply(data[fields],function(x) all(nzchar(as.character(x))),logical(1)))) stop("Complete clinical labels/groups required")
}

# A dose-response curve (including an already-fitted restricted cubic spline), not
# a spline estimator: exported reference, coordinates and uncertainty stay unchanged.
medpaper_dose_response <- function(data, x_label, y_label, null=NULL,
                                   ref_exposure=NULL, p_label=NULL,
                                   distribution_data=NULL, dist_bins=30L, dist_height=0.28) {
  medpaper_check_numeric(data,c("exposure","estimate","lower","upper"))
  medpaper_plot_groups(data,"group")
  if(any(data$lower>data$estimate | data$estimate>data$upper) || anyDuplicated(data[c("group","exposure")])) stop("Complete unique dose/interval coordinates required")
  data$group <- medpaper_label(data$group)
  x_label <- medpaper_label(x_label)
  y_label <- medpaper_label(y_label)
  p <- ggplot2::ggplot(data,ggplot2::aes(x=exposure,y=estimate,colour=group,fill=group,group=group)) +
    ggplot2::geom_ribbon(ggplot2::aes(ymin=lower,ymax=upper),alpha=.15,colour=NA) +
    ggplot2::geom_line(linewidth=.5) + ggplot2::labs(x=x_label,y=y_label) + medpaper_theme()
  if(!is.null(null)) {
    if(length(null)!=1L || !is.finite(null)) stop("Explicit finite reference value required")
    p <- p+ggplot2::geom_hline(yintercept=null,linetype="dashed",linewidth=.3)
  }
  if(!is.null(ref_exposure)) {
    if(length(ref_exposure)!=1L || !is.finite(ref_exposure)) stop("Explicit finite ref_exposure required")
    p <- p + ggplot2::geom_vline(xintercept=ref_exposure, linetype="dotted", linewidth=.35, colour="grey35")
  }
  if(!is.null(p_label) && nzchar(trimws(p_label))) {
    x_rng <- range(data$exposure, na.rm=TRUE)
    y_rng <- range(c(data$lower, data$upper), na.rm=TRUE)
    p <- p + ggplot2::annotate(
      "text", x=x_rng[1] + 0.03 * diff(x_rng), y=y_rng[2] - 0.05 * diff(y_rng),
      label=trimws(p_label), hjust=0, vjust=1, size=8.3/ggplot2::.pt, colour="black")
  }
  if(is.null(distribution_data)) return(p)

  medpaper_require("patchwork")
  medpaper_check_numeric(distribution_data, "exposure")
  x_lims <- range(c(data$exposure, distribution_data$exposure), na.rm=TRUE)
  p_top <- p +
    ggplot2::coord_cartesian(xlim=x_lims) +
    ggplot2::labs(x=NULL) +
    ggplot2::theme(axis.text.x=ggplot2::element_blank(),
                   axis.ticks.x=ggplot2::element_blank(),
                   plot.margin=ggplot2::margin(2, 4, 1, 4, unit="mm"))
  p_hist <- ggplot2::ggplot(distribution_data, ggplot2::aes(x=exposure)) +
    ggplot2::geom_histogram(bins=as.integer(dist_bins), fill="grey78", colour="grey30", linewidth=0.25) +
    ggplot2::coord_cartesian(xlim=x_lims) +
    ggplot2::labs(x=x_label, y="Count") +
    medpaper_theme() +
    ggplot2::theme(plot.margin=ggplot2::margin(0.5, 4, 2.5, 4, unit="mm"))
  if(!is.null(ref_exposure)) {
    p_hist <- p_hist + ggplot2::geom_vline(xintercept=ref_exposure, linetype="dotted", linewidth=.35, colour="grey35")
  }
  composed <- patchwork::wrap_plots(p_top, p_hist, ncol=1L, heights=c(1, dist_height))
  list(plot=composed, panels=list(p_top, p_hist))
}

medpaper_rcs_composite <- medpaper_dose_response

medpaper_decision_curve <- function(data, y_label="Net benefit") {
  medpaper_check_numeric(data,c("threshold","net_benefit"));medpaper_plot_groups(data,"group")
  if(any(data$threshold<=0 | data$threshold>=1) || anyDuplicated(data[c("group","threshold")])) stop("Unique source thresholds strictly between zero and one required")
  data$group <- medpaper_label(data$group)
  y_label <- medpaper_label(y_label)
  ggplot2::ggplot(data,ggplot2::aes(x=threshold,y=net_benefit,colour=group,group=group)) +
    ggplot2::geom_line(linewidth=.5) + ggplot2::labs(x="Threshold probability",y=y_label) + medpaper_theme()
}

medpaper_balance <- function(data, threshold=NULL, absolute=TRUE) {
  medpaper_check_numeric(data,"smd");medpaper_plot_groups(data,c("variable","group"))
  if(length(absolute)!=1L || !is.logical(absolute) || is.na(absolute) || anyDuplicated(data[c("group","variable")])) stop("Unique source variable/sample statistics and logical scale required")
  if(absolute) data$smd <- abs(data$smd)
  data$variable <- medpaper_label(data$variable)
  data$group <- medpaper_label(data$group)
  data$variable <- factor(data$variable,levels=rev(unique(data$variable)))
  p <- ggplot2::ggplot(data,ggplot2::aes(x=smd,y=variable,colour=group,shape=group)) +
    ggplot2::geom_point(size=2) + ggplot2::labs(x=if(absolute) "Absolute standardized mean difference" else "Standardized mean difference",y=NULL) + medpaper_theme()
  if(!is.null(threshold)) {
    if(length(threshold)!=1L || !is.finite(threshold) || threshold<=0) stop("Use the study's explicit positive balance threshold")
    p <- p+ggplot2::geom_vline(xintercept=if(absolute) threshold else c(-threshold,threshold),linetype="dashed",linewidth=.3)
  }
  p
}
