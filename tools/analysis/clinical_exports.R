# Method-agnostic R fact packaging helpers for 03_analysis/code/*.R producers.
# Imposes ZERO assumptions on study design, statistical model family, or figure type:
# execute whatever methods the S05/S07 comparator literature and data require, then
# package reportable scalar values with explicit clinical/scientific context.

medpaper_context <- function(outcome = NULL, population = NULL, comparison = NULL,
                             model = NULL, timepoint = NULL, unit = NULL,
                             denominator = NULL, percentage_basis = NULL,
                             interval_level = NULL) {
  ctx <- list(
    outcome = outcome, population = population, comparison = comparison,
    model = model, timepoint = timepoint, unit = unit, denominator = denominator
  )
  ctx <- Filter(Negate(is.null), ctx)
  if (!is.null(percentage_basis)) ctx$percentage_basis <- percentage_basis
  if (!is.null(interval_level)) ctx$interval_level <- interval_level
  ctx
}

medpaper_fact <- function(values, outcome = NULL, population = NULL, comparison = NULL,
                          model = NULL, timepoint = NULL, unit = NULL,
                          denominator = NULL, percentage_basis = NULL,
                          interval_level = NULL, ctx = NULL, data = NULL) {
  if (is.numeric(values) && !is.null(names(values))) values <- as.list(values)
  if (!is.list(values) || !length(values) || is.null(names(values)))
    stop("values must be a non-empty named list (or named numeric vector) of finite scalars")
  clean_vals <- list()
  for (nm in names(values)) {
    v <- values[[nm]]
    if (is.null(v)) next
    if (!is.numeric(v) || length(v) != 1L || !is.finite(v))
      stop("Non-finite or non-scalar numeric value in medpaper_fact: ", nm)
    clean_vals[[nm]] <- v
  }
  if (!length(clean_vals)) stop("medpaper_fact requires at least one finite numeric value")

  merged <- if (is.list(ctx)) ctx else list()
  overrides <- medpaper_context(
    outcome = outcome, population = population, comparison = comparison,
    model = model, timepoint = timepoint, unit = unit, denominator = denominator,
    percentage_basis = percentage_basis, interval_level = interval_level
  )
  for (k in names(overrides)) merged[[k]] <- overrides[[k]]

  req_keys <- c("outcome", "population", "comparison", "model", "timepoint", "unit", "denominator")
  for (k in req_keys) {
    val <- merged[[k]]
    if (!is.character(val) || length(val) != 1L || !nzchar(trimws(val)))
      stop("Missing context string for '", k, "' in medpaper_fact")
    merged[[k]] <- trimws(val)
  }
  if (!is.null(merged$percentage_basis)) {
    merged$percentage_basis <- trimws(as.character(merged$percentage_basis))
  }
  out <- list(context = merged, values = clean_vals)
  if (!is.null(data)) out$data <- data
  out
}

medpaper_fact_node <- medpaper_fact
