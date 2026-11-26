# Standardized R clinical statistical exporters producing study_facts-ready {context, values} nodes.
# Source alongside tools/analysis/results.R inside 03_analysis/code/*.R producers.

medpaper_fact_node <- function(values, outcome, population, comparison, model,
                               timepoint, unit, denominator,
                               percentage_basis = NULL, interval_level = NULL) {
  if (!is.list(values) || !length(values) || is.null(names(values)))
    stop("values must be a non-empty named list of finite scalars")
  for (nm in names(values)) {
    v <- values[[nm]]
    if (is.null(v)) next
    if (!is.numeric(v) || length(v) != 1L || !is.finite(v))
      stop("Non-finite or non-scalar numeric value in medpaper_fact_node: ", nm)
  }
  req <- list(outcome = outcome, population = population, comparison = comparison,
              model = model, timepoint = timepoint, unit = unit, denominator = denominator)
  for (k in names(req)) {
    if (!is.character(req[[k]]) || length(req[[k]]) != 1L || !nzchar(trimws(req[[k]])))
      stop("Missing clinical context string for '", k, "'")
    req[[k]] <- trimws(req[[k]])
  }
  if (!is.null(percentage_basis) && nzchar(trimws(as.character(percentage_basis))))
    req$percentage_basis <- trimws(as.character(percentage_basis))
  if (!is.null(interval_level) && is.numeric(interval_level) && length(interval_level) == 1L)
    req$interval_level <- interval_level
  list(context = req, values = values)
}

# Continuous baseline / outcome variable exporter:
# Computes n, missing, mean/SD, median/IQR (Q25-Q75), two-group pooled SMD, and normality hint.
medpaper_export_continuous <- function(x, group = NULL, var_label, population,
                                       timepoint = "Baseline", unit = "units",
                                       include_p = FALSE) {
  if (!is.numeric(x)) stop("medpaper_export_continuous requires numeric vector x")
  summ_one <- function(v, comp_lbl, denom_lbl) {
    n_tot <- length(v)
    ok <- v[!is.na(v) & is.finite(v)]
    n_ok <- length(ok)
    n_miss <- n_tot - n_ok
    if (n_ok == 0L) stop("No non-missing observations for ", var_label, " in ", comp_lbl)
    qs <- as.numeric(stats::quantile(ok, probs = c(0.25, 0.50, 0.75), names = FALSE, type = 7))
    vals <- list(
      n_total = as.integer(n_tot),
      n_nonmissing = as.integer(n_ok),
      n_missing = as.integer(n_miss),
      mean = mean(ok),
      sd = if (n_ok > 1L) stats::sd(ok) else 0.0,
      median = qs[2],
      q25 = qs[1],
      q75 = qs[3],
      iqr = qs[3] - qs[1]
    )
    if (n_ok >= 3L && n_ok <= 5000L && stats::sd(ok) > 0) {
      vals$shapiro_p <- as.numeric(stats::shapiro.test(ok)$p.value)
    }
    medpaper_fact_node(
      values = vals, outcome = var_label, population = population,
      comparison = comp_lbl, model = "Descriptive summary",
      timepoint = timepoint, unit = unit, denominator = denom_lbl
    )
  }

  out <- list(
    overall = summ_one(x, "Overall cohort", paste0(sum(!is.na(x)), " non-missing observations"))
  )
  if (!is.null(group)) {
    if (length(group) != length(x)) stop("group length must match x")
    g_chr <- as.character(group)
    lvls <- if (is.factor(group)) levels(group) else unique(g_chr[!is.na(g_chr)])
    out$groups <- list()
    for (lv in lvls) {
      sub_x <- x[!is.na(g_chr) & g_chr == lv]
      slug <- gsub("[^A-Za-z0-9]+", "_", tolower(lv))
      out$groups[[slug]] <- summ_one(
        sub_x, paste0("Group: ", lv),
        paste0(sum(!is.na(sub_x)), " non-missing in ", lv)
      )
    }
    if (length(lvls) == 2L) {
      g1 <- x[!is.na(g_chr) & g_chr == lvls[1] & is.finite(x)]
      g2 <- x[!is.na(g_chr) & g_chr == lvls[2] & is.finite(x)]
      if (length(g1) > 1L && length(g2) > 1L) {
        s_pool <- sqrt((stats::var(g1) + stats::var(g2)) / 2)
        smd_val <- if (s_pool > 0) (mean(g1) - mean(g2)) / s_pool else 0.0
        comp_vals <- list(
          n_group1 = as.integer(length(g1)),
          n_group2 = as.integer(length(g2)),
          smd = smd_val,
          abs_smd = abs(smd_val)
        )
        if (isTRUE(include_p)) {
          comp_vals$p_welch <- as.numeric(stats::t.test(g1, g2)$p.value)
          comp_vals$p_wilcox <- as.numeric(stats::wilcox.test(g1, g2, exact = FALSE)$p.value)
        }
        out$comparison <- medpaper_fact_node(
          values = comp_vals, outcome = var_label, population = population,
          comparison = paste0(lvls[1], " vs ", lvls[2]),
          model = "Two-group standardized mean difference",
          timepoint = timepoint, unit = "standardized mean difference",
          denominator = paste0(length(g1) + length(g2), " non-missing observations")
        )
      }
    }
  }
  out
}

# Categorical baseline / outcome variable exporter (exports ALL levels with n, denom, pct, and SMD).
medpaper_export_categorical <- function(x, group = NULL, var_label, population,
                                        timepoint = "Baseline", levels = NULL,
                                        include_p = FALSE) {
  x_chr <- if (is.logical(x)) ifelse(is.na(x), NA_character_, ifelse(x, "Yes", "No")) else as.character(x)
  lvls <- if (!is.null(levels)) as.character(levels) else if (is.factor(x)) base::levels(x) else unique(x_chr[!is.na(x_chr)])
  if (any(!x_chr[!is.na(x_chr)] %in% lvls)) stop("Declared levels omit observed values in ", var_label)

  pack_slice <- function(vec, comp_lbl) {
    n_tot <- length(vec)
    ok <- vec[!is.na(vec)]
    n_ok <- length(ok)
    vals <- list(n_total = as.integer(n_tot), n_nonmissing = as.integer(n_ok), n_missing = as.integer(n_tot - n_ok))
    for (lv in lvls) {
      s <- gsub("[^A-Za-z0-9]+", "_", tolower(lv))
      cnt <- sum(ok == lv)
      vals[[paste0("n_", s)]] <- as.integer(cnt)
      vals[[paste0("pct_", s)]] <- if (n_ok > 0L) (100.0 * cnt / n_ok) else 0.0
    }
    medpaper_fact_node(
      values = vals, outcome = var_label, population = population,
      comparison = comp_lbl, model = "Descriptive proportions",
      timepoint = timepoint, unit = "percentage",
      denominator = paste0(n_ok, " non-missing observations"),
      percentage_basis = paste0("Available non-missing ", var_label, " observations (N = ", n_ok, ") at ", timepoint)
    )
  }

  out <- list(overall = pack_slice(x_chr, "Overall cohort"))
  if (!is.null(group)) {
    if (length(group) != length(x_chr)) stop("group length must match x")
    g_chr <- as.character(group)
    g_lvls <- if (is.factor(group)) base::levels(group) else unique(g_chr[!is.na(g_chr)])
    out$groups <- list()
    for (gl in g_lvls) {
      slug <- gsub("[^A-Za-z0-9]+", "_", tolower(gl))
      out$groups[[slug]] <- pack_slice(x_chr[!is.na(g_chr) & g_chr == gl], paste0("Group: ", gl))
    }
    if (length(g_lvls) == 2L) {
      v1 <- x_chr[!is.na(g_chr) & g_chr == g_lvls[1] & !is.na(x_chr)]
      v2 <- x_chr[!is.na(g_chr) & g_chr == g_lvls[2] & !is.na(x_chr)]
      if (length(v1) > 0L && length(v2) > 0L) {
        smds <- vapply(lvls, function(lv) {
          p1 <- mean(v1 == lv); p2 <- mean(v2 == lv)
          denom <- sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
          if (denom > 0) (p1 - p2) / denom else 0.0
        }, numeric(1))
        c_vals <- list(max_abs_smd = max(abs(smds)))
        if (isTRUE(include_p)) {
          tbl <- table(factor(x_chr[!is.na(g_chr) & !is.na(x_chr)], levels = lvls),
                       factor(g_chr[!is.na(g_chr) & !is.na(x_chr)], levels = g_lvls))
          c_vals$p_chisq <- suppressWarnings(as.numeric(stats::chisq.test(tbl)$p.value))
        }
        out$comparison <- medpaper_fact_node(
          values = c_vals, outcome = var_label, population = population,
          comparison = paste0(g_lvls[1], " vs ", g_lvls[2]),
          model = "Categorical standardized mean difference",
          timepoint = timepoint, unit = "standardized mean difference",
          denominator = paste0(length(v1) + length(v2), " non-missing observations")
        )
      }
    }
  }
  out
}

# Generalized linear model effect exporter (OR for binomial logit, RR for log/poisson, beta for gaussian).
medpaper_export_glm_effect <- function(fit, term, outcome, population, comparison,
                                       model_label, timepoint, n_events = NULL) {
  if (!inherits(fit, "glm")) stop("fit must be a glm object")
  sm <- stats::coef(summary(fit))
  if (!term %in% rownames(sm)) stop("Term '", term, "' not found in glm coefficients")
  beta <- unname(sm[term, 1L])
  se <- unname(sm[term, 2L])
  pval <- unname(sm[term, ncol(sm)])
  z <- stats::qnorm(0.975)
  fam <- fit$family$family
  lnk <- fit$family$link
  is_exp <- lnk %in% c("logit", "log")
  est <- if (is_exp) exp(beta) else beta
  lo <- if (is_exp) exp(beta - z * se) else (beta - z * se)
  hi <- if (is_exp) exp(beta + z * se) else (beta + z * se)
  unit_lbl <- if (fam %in% c("binomial", "quasibinomial") && lnk == "logit") {
    "odds ratio"
  } else if (lnk == "log") {
    "risk ratio"
  } else {
    "regression slope"
  }
  eff_key <- if (unit_lbl == "odds ratio") "or" else if (unit_lbl == "risk ratio") "rr" else "beta"
  n_tot <- as.integer(stats::nobs(fit))
  vals <- list(n_total = n_tot)
  if (!is.null(n_events)) vals$n_events <- as.integer(n_events)
  vals[[eff_key]] <- est
  vals$ci_low <- lo
  vals$ci_high <- hi
  vals$p_value <- pval
  medpaper_fact_node(
    values = vals, outcome = outcome, population = population,
    comparison = comparison, model = model_label, timepoint = timepoint,
    unit = unit_lbl, denominator = paste0(n_tot, " observations in ", model_label)
  )
}

# Cox proportional hazards exporter with automatic Schoenfeld residual PH assumption check.
medpaper_export_cox_hr <- function(fit, term, outcome, population, comparison,
                                   model_label, timepoint) {
  if (!requireNamespace("survival", quietly = TRUE)) stop("survival package is required")
  if (!inherits(fit, "coxph")) stop("fit must be a survival::coxph object")
  sm <- summary(fit)
  if (!term %in% rownames(sm$coefficients)) stop("Term '", term, "' not found in coxph model")
  hr <- unname(sm$conf.int[term, "exp(coef)"])
  lo <- unname(sm$conf.int[term, "lower .95"])
  hi <- unname(sm$conf.int[term, "upper .95"])
  pval <- unname(sm$coefficients[term, "Pr(>|z|)"])
  n_tot <- as.integer(fit$n)
  n_ev <- as.integer(fit$nevent)
  vals <- list(
    n_total = n_tot,
    n_events = n_ev,
    hr = hr,
    ci_low = lo,
    ci_high = hi,
    p_value = pval
  )
  zph <- tryCatch(survival::cox.zph(fit), error = function(e) NULL)
  if (!is.null(zph) && is.matrix(zph$table)) {
    if (term %in% rownames(zph$table)) vals$ph_p_term <- unname(zph$table[term, "p"])
    if ("GLOBAL" %in% rownames(zph$table)) vals$ph_p_global <- unname(zph$table["GLOBAL", "p"])
  }
  medpaper_fact_node(
    values = vals, outcome = outcome, population = population,
    comparison = comparison, model = model_label, timepoint = timepoint,
    unit = "hazard ratio", denominator = paste0(n_tot, " participants (", n_ev, " events)")
  )
}

# Restricted cubic spline (RCS) summary exporter (overall & nonlinearity P + grid coordinates).
medpaper_export_rcs_summary <- function(curve_df, p_overall, p_nonlinear, ref_exposure,
                                        outcome, population, model_label, timepoint,
                                        unit = "hazard ratio", denominator) {
  req_cols <- c("exposure", "estimate", "lower", "upper")
  if (!is.data.frame(curve_df) || !nrow(curve_df) || !all(req_cols %in% names(curve_df)))
    stop("curve_df must contain exposure, estimate, lower, upper")
  node <- medpaper_fact_node(
    values = list(
      ref_exposure = as.numeric(ref_exposure),
      p_overall = as.numeric(p_overall),
      p_nonlinear = as.numeric(p_nonlinear),
      min_exposure = min(curve_df$exposure),
      max_exposure = max(curve_df$exposure)
    ),
    outcome = outcome, population = population,
    comparison = paste0("Continuous spline relative to reference ", ref_exposure),
    model = model_label, timepoint = timepoint, unit = unit, denominator = denominator
  )
  node$curve <- curve_df
  node
}
