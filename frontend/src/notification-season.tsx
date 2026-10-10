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

export const notificationAnimals = ["duck", "mallard", "duckling", "rabbit", "cat", "fox", "bear", "penguin", "owl", "frog"] as const;
export type NotificationAnimal = typeof notificationAnimals[number];

export function nextNotificationAnimal(previous?: NotificationAnimal): NotificationAnimal {
  const choices = notificationAnimals.filter((animal) => animal !== previous);
  return choices[Math.floor(Math.random() * choices.length)];
}

function AnimalArt({ animal }: { animal: NotificationAnimal }) {
  if (animal === "duck") return <image href="/notification-duck.svg" width="64" height="64" />;
  if (animal === "mallard" || animal === "duckling") return <g stroke="#182d22" strokeWidth="2">
    <path d="M19 46L16 56H27M39 47L44 56H53" fill="none" stroke="#ff9c32" strokeWidth="4" />
    <path d="M8 30L19 35C25 24 44 25 50 36C60 53 16 56 9 40Z" fill={animal === "mallard" ? "#bb8962" : "#fff29a"} />
    <circle cx="43" cy="20" r={animal === "mallard" ? 13 : 11} fill={animal === "mallard" ? "#258765" : "#fff29a"} />
    <path d="M52 22H62L59 28H51Z" fill="#ff9c32" /><circle cx="47" cy="18" r="2" fill="#14251c" />
    <path d="M20 38Q30 30 39 39Q30 47 20 38" fill={animal === "mallard" ? "#3c739e" : "#ffd967"} />
    {animal === "mallard" && <path d="M33 30H50" stroke="#fff8e8" strokeWidth="3" />}
  </g>;
  const colors = { rabbit: "#e6dce8", cat: "#829ab0", fox: "#ef9952", bear: "#ba936d", penguin: "#233847", owl: "#bd9980", frog: "#77c982" };
  const color = colors[animal];
  return <g stroke="#182d22" strokeWidth="2" strokeLinejoin="round">
    {animal === "rabbit" && <g fill={color}><ellipse cx="34" cy="10" rx="5" ry="9" /><ellipse cx="48" cy="10" rx="5" ry="9" /></g>}
    {(animal === "cat" || animal === "fox") && <path d="M29 22L28 7L39 15L50 7L55 24" fill={color} />}
    {animal === "bear" && <g fill={color}><circle cx="30" cy="14" r="6" /><circle cx="52" cy="14" r="6" /></g>}
    {animal === "frog" && <g fill={color}><circle cx="31" cy="14" r="6" /><circle cx="50" cy="14" r="6" /></g>}
    {animal === "fox" && <path d="M22 43Q0 52 5 27Q18 30 24 41" fill={color} />}
    {animal === "cat" && <path d="M23 44Q3 52 8 32" fill="none" stroke={color} strokeWidth="6" />}
    {animal === "rabbit" && <circle cx="18" cy="43" r="6" fill="#fff8f5" />}
    <ellipse cx="34" cy="40" rx={animal === "penguin" ? 14 : 17} ry="15" fill={color} />
    <ellipse cx="36" cy="43" rx="10" ry="11" fill={animal === "frog" ? "#c6e99b" : "#fff0d7"} stroke="none" />
    <path d="M24 51L20 57H30M42 51L46 57H54" fill="none" stroke={animal === "penguin" || animal === "owl" ? "#eea44f" : color} strokeWidth="5" />
    <ellipse cx="41" cy="22" rx="15" ry="13" fill={color} />
    {animal === "owl" && <g fill="#fff0d7"><circle cx="34" cy="21" r="7" /><circle cx="48" cy="21" r="7" /></g>}
    {animal === "fox" && <path d="M28 24L41 32L54 24L47 21L41 26L34 21Z" fill="#fff0d7" stroke="none" />}
    <g fill="#15251d" stroke="none"><circle cx="35" cy="21" r="2.3" /><circle cx="48" cy="21" r="2.3" /></g>
    {animal === "penguin" || animal === "owl" ? <path d="M39 25H45L42 30Z" fill="#eea44f" /> : animal === "frog" ? <path d="M34 27Q41 32 49 27" fill="none" /> : <g><ellipse cx="42" cy="27" rx="3" ry="2" fill="#51392d" /><path d="M42 29V32" /></g>}
    {animal === "cat" && <path d="M29 26L22 24M29 29L22 30M53 26L60 24M53 29L60 30" />}
    {animal === "penguin" && <path d="M21 33L14 45M47 33L54 45" stroke={color} strokeWidth="5" />}
    {animal === "owl" && <path d="M22 34L28 43M46 34L42 43" fill="none" />}
  </g>;
}

export function NotificationSeasonArt({ season, animal = "duck" }: { season: NotificationSeason; animal?: NotificationAnimal }) {
  return <svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">
    <AnimalArt animal={animal} />
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