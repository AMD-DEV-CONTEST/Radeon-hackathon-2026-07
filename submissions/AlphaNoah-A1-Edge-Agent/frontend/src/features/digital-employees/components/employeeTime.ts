export function formatEmployeeTime(
  value: string,
  locale: "zh-CN" | "en-US",
  includeDate = false,
): string {
  const sourceClock = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/,
  );
  if (!sourceClock) {
    return value;
  }

  const [, year, month, day, hour, minute, second = "0"] =
    sourceClock;
  const date = new Date(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    ),
  );

  return new Intl.DateTimeFormat(locale, {
    ...(includeDate
      ? {
          year: "numeric",
          month: "short",
          day: "numeric",
        }
      : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date);
}
