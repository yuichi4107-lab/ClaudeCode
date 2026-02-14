"""データクラス定義"""

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Race:
    race_id: str
    race_date: date
    venue_code: str
    race_number: int
    venue_name: str = ""
    race_name: str = ""
    surface: str = ""
    distance: int = 0
    track_condition: str = ""
    weather: str = ""
    race_class: str = ""
    race_class_code: int = 0
    age_condition: str = ""
    weight_rule: str = ""
    num_runners: int = 0
    prize_1st: float = 0.0


@dataclass
class RaceResult:
    race_id: str
    horse_id: str
    horse_name: str = ""
    finish_position: int | None = None
    post_position: int = 0
    horse_number: int = 0
    sex: str = ""
    age: int = 0
    weight_carried: float = 0.0
    jockey_id: str = ""
    jockey_name: str = ""
    trainer_id: str = ""
    trainer_name: str = ""
    finish_time: float | None = None
    margin: str = ""
    last_3f: float | None = None
    horse_weight: int | None = None
    weight_change: int | None = None
    odds: float | None = None
    popularity: int | None = None
    running_style: str = ""
    corner_positions: str = ""
    prize_money: float = 0.0


@dataclass
class Horse:
    horse_id: str
    horse_name: str
    sex: str = ""
    birth_year: int = 0
    coat_color: str = ""
    sire_id: str = ""
    sire_name: str = ""
    dam_id: str = ""
    dam_name: str = ""
    damsire_id: str = ""
    damsire_name: str = ""
    owner: str = ""
    breeder: str = ""
    total_wins: int = 0
    total_runs: int = 0
    total_earnings: float = 0.0


@dataclass
class Jockey:
    jockey_id: str
    jockey_name: str
    birth_year: int = 0
    affiliation: str = ""
    total_wins: int = 0
    total_runs: int = 0
    win_rate: float = 0.0


@dataclass
class Trainer:
    trainer_id: str
    trainer_name: str
    affiliation: str = ""
    total_wins: int = 0
    total_runs: int = 0
    win_rate: float = 0.0


@dataclass
class Win5Event:
    event_id: str
    event_date: date
    race1_id: str = ""
    race2_id: str = ""
    race3_id: str = ""
    race4_id: str = ""
    race5_id: str = ""
    payout: float | None = None
    carryover: float | None = None
    num_winners: int | None = None
    total_sales: float | None = None


@dataclass
class Win5Bet:
    event_id: str
    bet_date: date
    selections: str  # JSON: [[1,3],[2],[1,5,8],[3],[1,2]]
    num_combinations: int
    total_cost: int
    is_hit: bool = False
    payout: float = 0.0
    model_version: str = ""


@dataclass
class ModelInfo:
    model_id: str
    model_name: str
    version: str
    model_path: str
    train_start: date | None = None
    train_end: date | None = None
    auc: float = 0.0
    logloss: float = 0.0
    accuracy: float = 0.0
    feature_count: int = 0
    params: str = ""  # JSON
    is_active: bool = False
