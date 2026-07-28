const NAGOYA = {
  name: "名古屋市",
  latitude: 35.1815,
  longitude: 136.9066,
};

let activePlace = { ...NAGOYA };

const els = {
  locationName: document.querySelector("#locationName"),
  weatherMark: document.querySelector("#weatherMark"),
  conditionText: document.querySelector("#conditionText"),
  currentTemp: document.querySelector("#currentTemp"),
  updatedAt: document.querySelector("#updatedAt"),
  feelsLike: document.querySelector("#feelsLike"),
  rainNow: document.querySelector("#rainNow"),
  humidity: document.querySelector("#humidity"),
  wind: document.querySelector("#wind"),
  statusPanel: document.querySelector("#statusPanel"),
  statusText: document.querySelector("#statusText"),
  hourlyDate: document.querySelector("#hourlyDate"),
  hourlyList: document.querySelector("#hourlyList"),
  dailyList: document.querySelector("#dailyList"),
  locationButton: document.querySelector("#locationButton"),
  refreshButton: document.querySelector("#refreshButton"),
};

const weatherLabels = new Map([
  [0, ["快晴", "sunny"]],
  [1, ["晴れ", "sunny"]],
  [2, ["薄曇り", "cloudy"]],
  [3, ["曇り", "cloudy"]],
  [45, ["霧", "fog"]],
  [48, ["霧氷", "fog"]],
  [51, ["弱い霧雨", "rain"]],
  [53, ["霧雨", "rain"]],
  [55, ["強い霧雨", "rain"]],
  [61, ["小雨", "rain"]],
  [63, ["雨", "rain"]],
  [65, ["強い雨", "rain"]],
  [66, ["冷たい雨", "rain"]],
  [67, ["強い冷たい雨", "rain"]],
  [71, ["小雪", "snow"]],
  [73, ["雪", "snow"]],
  [75, ["強い雪", "snow"]],
  [77, ["雪粒", "snow"]],
  [80, ["にわか雨", "rain"]],
  [81, ["強いにわか雨", "rain"]],
  [82, ["激しいにわか雨", "rain"]],
  [85, ["にわか雪", "snow"]],
  [86, ["強いにわか雪", "snow"]],
  [95, ["雷雨", "storm"]],
  [96, ["雷雨・ひょう", "storm"]],
  [99, ["激しい雷雨・ひょう", "storm"]],
]);

const markByType = {
  sunny: "☀",
  cloudy: "☁",
  fog: "≋",
  rain: "☂",
  snow: "❄",
  storm: "⚡",
};

function forecastUrl(place) {
  const params = new URLSearchParams({
    latitude: String(place.latitude),
    longitude: String(place.longitude),
    current: [
      "temperature_2m",
      "relative_humidity_2m",
      "apparent_temperature",
      "precipitation",
      "rain",
      "weather_code",
      "wind_speed_10m",
      "wind_direction_10m",
      "is_day",
    ].join(","),
    hourly: [
      "temperature_2m",
      "apparent_temperature",
      "precipitation_probability",
      "weather_code",
      "wind_speed_10m",
    ].join(","),
    daily: [
      "weather_code",
      "temperature_2m_max",
      "temperature_2m_min",
      "precipitation_probability_max",
      "sunrise",
      "sunset",
    ].join(","),
    forecast_days: "7",
    timezone: "Asia/Tokyo",
  });
  return `https://api.open-meteo.com/v1/forecast?${params.toString()}`;
}

function weatherInfo(code) {
  const [label, type] = weatherLabels.get(code) ?? ["不明", "cloudy"];
  return {
    label,
    mark: markByType[type],
  };
}

function formatHour(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDay(value, index) {
  if (index === 0) return "今日";
  if (index === 1) return "明日";
  return new Intl.DateTimeFormat("ja-JP", {
    weekday: "short",
    month: "numeric",
    day: "numeric",
  }).format(new Date(`${value}T00:00:00+09:00`));
}

function round(value, digits = 0) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return value.toFixed(digits);
}

function setStatus(message, isError = false) {
  els.statusText.textContent = message;
  els.statusPanel.hidden = !message;
  els.statusPanel.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function renderCurrent(data) {
  const current = data.current;
  const info = weatherInfo(current.weather_code);
  els.locationName.textContent = activePlace.name;
  els.weatherMark.textContent = info.mark;
  els.conditionText.textContent = info.label;
  els.currentTemp.textContent = round(current.temperature_2m);
  els.updatedAt.textContent = `${formatHour(current.time)} 更新`;
  els.feelsLike.textContent = `${round(current.apparent_temperature)}℃`;
  els.rainNow.textContent = `${round(current.precipitation ?? current.rain, 1)}mm`;
  els.humidity.textContent = `${round(current.relative_humidity_2m)}%`;
  els.wind.textContent = `${round(current.wind_speed_10m, 1)}m/s`;
}

function renderHourly(data) {
  const now = new Date(data.current.time).getTime();
  const rows = data.hourly.time
    .map((time, index) => ({
      time,
      timeMs: new Date(time).getTime(),
      temp: data.hourly.temperature_2m[index],
      rain: data.hourly.precipitation_probability[index],
      code: data.hourly.weather_code[index],
    }))
    .filter((row) => row.timeMs >= now)
    .slice(0, 12);

  els.hourlyDate.textContent = new Intl.DateTimeFormat("ja-JP", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
  }).format(new Date(data.current.time));

  els.hourlyList.innerHTML = rows
    .map((row) => {
      const info = weatherInfo(row.code);
      return `
        <article class="hour-card">
          <time datetime="${row.time}">${formatHour(row.time)}</time>
          <div class="icon" aria-hidden="true">${info.mark}</div>
          <strong>${round(row.temp)}℃</strong>
          <span>降水 ${round(row.rain)}%</span>
        </article>
      `;
    })
    .join("");
}

function renderDaily(data) {
  const mins = data.daily.temperature_2m_min;
  const maxes = data.daily.temperature_2m_max;
  const low = Math.min(...mins);
  const high = Math.max(...maxes);
  const span = Math.max(1, high - low);

  els.dailyList.innerHTML = data.daily.time
    .map((date, index) => {
      const min = mins[index];
      const max = maxes[index];
      const width = Math.max(18, ((max - low) / span) * 82 + 18);
      const info = weatherInfo(data.daily.weather_code[index]);
      return `
        <article class="day-row">
          <div class="day-name">${formatDay(date, index)}</div>
          <div class="day-icon" aria-hidden="true">${info.mark}</div>
          <div class="day-temps">
            <div class="bar"><span style="width:${width}%"></span></div>
            <div class="temp-range"><span>${round(min)}℃</span><span>${round(max)}℃</span></div>
          </div>
          <div class="rain">${round(data.daily.precipitation_probability_max[index])}%</div>
        </article>
      `;
    })
    .join("");
}

async function loadWeather(place = activePlace) {
  activePlace = place;
  setStatus("天気を取得しています。");
  els.refreshButton.disabled = true;

  try {
    const response = await fetch(forecastUrl(place), { cache: "no-store" });
    if (!response.ok) throw new Error(`weather api ${response.status}`);
    const data = await response.json();
    renderCurrent(data);
    renderHourly(data);
    renderDaily(data);
    setStatus("");
  } catch (error) {
    console.error(error);
    setStatus("天気を取得できませんでした。通信状態を確認して、更新してください。", true);
  } finally {
    els.refreshButton.disabled = false;
  }
}

function useCurrentLocation() {
  if (!navigator.geolocation) {
    setStatus("このブラウザでは現在地を取得できません。", true);
    return;
  }

  setStatus("現在地を確認しています。");
  navigator.geolocation.getCurrentPosition(
    (position) => {
      loadWeather({
        name: "現在地",
        latitude: Number(position.coords.latitude.toFixed(4)),
        longitude: Number(position.coords.longitude.toFixed(4)),
      });
    },
    () => {
      setStatus("現在地の利用が許可されませんでした。名古屋市の天気を表示しています。", true);
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
  );
}

els.refreshButton.addEventListener("click", () => loadWeather(activePlace));
els.locationButton.addEventListener("click", useCurrentLocation);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  });
}

loadWeather();
