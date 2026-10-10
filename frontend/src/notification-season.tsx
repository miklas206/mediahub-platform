export type NotificationSeason = "winter" | "spring" | "summer" | "autumn" | "halloween" | "midsummer" | "christmas" | "newyear" | "valentine";

export function notificationSeason(date: Date): NotificationSeason {
  const month = date.getMonth() + 1;
  const day = date.getDate();
  if ((month === 12 && day >= 29) || (month === 1 && day <= 3)) return "newyear";
  if (month === 12) return "christmas";
  if (month === 10 && day >= 20) return "halloween";
  if (month === 6 && day >= 20 && day <= 24) return "midsummer";
  if (month === 2 && day >= 12 && day <= 14) return "valentine";
  if (month >= 3 && month <= 5) return "spring";
  if (month >= 6 && month <= 8) return "summer";
  if (month >= 9 && month <= 11) return "autumn";
  return "winter";
}

export function NotificationSeasonArt({ season }: { season: NotificationSeason }) {
  return <svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">
    <image href="/notification-duck.svg" width="64" height="64" />
    {season === "christmas" && <g><path d="M30 14Q33 0 48 3L56 12 46 8 46 14Z" fill="#eb4657" stroke="#7e172b" /><path d="M30 14H51" stroke="#fff7ec" strokeWidth="5" /><circle cx="56" cy="12" r="4" fill="#fff7ec" /><path d="M33 31H49L45 37H32Z" fill="#eb4657" /></g>}
    {season === "halloween" && <g><path d="M31 12L36 0 48 12Z" fill="#8b51c9" stroke="#301643" /><path d="M27 14H54" stroke="#301643" strokeWidth="5" /><path d="M33 10H47" stroke="#ffad3d" strokeWidth="3" /><path d="M11 34L20 30 30 36 39 31 45 42 29 47Z" fill="#301643" /><path d="M21 37L25 39M31 37L35 39" stroke="#ffad3d" strokeWidth="2" /></g>}
    {season === "winter" && <g><path d="M30 13Q31 1 45 4Q52 5 53 13Z" fill="#5cc9f2" /><path d="M30 14H53" stroke="#e5f8ff" strokeWidth="4" /><circle cx="41" cy="3" r="3" fill="#e5f8ff" /><path d="M31 30H49V35H39V46H33V35H31Z" fill="#5cc9f2" /></g>}
    {season === "spring" && <g stroke="#fff5ff" strokeWidth="3" fill="#f278b9"><circle cx="31" cy="12" r="4" /><circle cx="40" cy="9" r="4" /><circle cx="49" cy="12" r="4" /><path d="M17 40L25 45" stroke="#4da678" /></g>}
    {season === "summer" && <g><path d="M30 11Q42 1 52 11" fill="#f4e3a2" stroke="#bc8d3c" strokeWidth="3" /><path d="M25 13H57" stroke="#f4e3a2" strokeWidth="4" /><path d="M36 18H42V23H36ZM45 18H51V23H45Z" fill="#173a48" /><path d="M42 20H45" stroke="#173a48" strokeWidth="2" /></g>}
    {season === "autumn" && <g><path d="M29 13Q33 5 48 8L52 13Z" fill="#c46c3f" stroke="#713d2c" /><path d="M30 14H54" stroke="#713d2c" strokeWidth="3" /><path d="M31 30H49V35H40V44H34V35H31Z" fill="#cd763c" /><path d="M15 39Q21 29 27 37Q26 46 15 39Z" fill="#db8b42" /></g>}
    {season === "midsummer" && <g><path d="M29 13Q42 2 54 13" fill="none" stroke="#379a5e" strokeWidth="4" /><g fill="#fff5c9"><circle cx="31" cy="11" r="3" /><circle cx="39" cy="8" r="3" /><circle cx="47" cy="9" r="3" /><circle cx="53" cy="13" r="3" /></g><path d="M5 47Q0 39 6 32Q4 39 10 42Q12 37 13 35Q19 46 10 51Z" fill="#ff9536" /><path d="M7 48L10 41 12 48Z" fill="#ffe989" /></g>}
    {season === "newyear" && <g><path d="M32 14V4H48V14Z" fill="#142d35" stroke="#71f4c0" /><path d="M28 15H52M33 11H47" stroke="#71f4c0" strokeWidth="3" /><path d="M6 10V18M2 14H10M17 2V10M13 6H21" stroke="#ffd86d" strokeWidth="2" /><path d="M34 32L41 36 47 32V40L41 36 34 40Z" fill="#71f4c0" /></g>}
    {season === "valentine" && <g fill="#f26994"><path d="M4 12C-1 6 7 2 10 7C13 2 21 6 16 12L10 18Z" /><path d="M18 38C14 33 20 30 23 34C26 30 32 33 28 38L23 43Z" /></g>}
  </svg>;
}