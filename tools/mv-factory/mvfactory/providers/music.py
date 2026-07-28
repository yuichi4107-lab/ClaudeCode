"""工程1: 曲生成プロバイダー抽象化。

song_source: suno_api | suno_bridge | manual の3モードを共通インターフェースの
下に隠蔽する。どちらのモードでも後続工程(工程2以降)へは同一形式
(song.mp3 + lyrics.txt + song_meta.json) で渡す。

著作権・商用利用リスク(残論点、要件定義書 6章参照):
  - Suno生成楽曲はSuno社のサービス利用規約・商用利用条件(サブスクプラン等)に従う。
  - AI音楽学習データを巡る業界訴訟(UMG/Sony継続中)は本パイプラインでは解消されない。
  - 収益化・公開前提のMVに使う場合はSuno公式の利用規約を確認し、
    必要であればオーナーの明示承認を得ること。
  - 本モジュールはこのリスクを判断・保証しない。呼び出し側(オーナー)の責任で運用する。
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import log, write_json


class MusicProviderError(RuntimeError):
    """曲生成/投入時のエラー。呼び出し側で全自動フローを止める根拠にする。"""


class MusicProvider(ABC):
    """曲生成プロバイダーの抽象基底クラス。"""

    @abstractmethod
    def generate(self, project: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
        """曲を用意し、out_dir に song.mp3 / lyrics.txt / song_meta.json を書き出す。

        Returns:
            song_meta dict (song_meta.json と同内容)
        """
        raise NotImplementedError


class SunoApiProvider(MusicProvider):
    """Suno公式API呼び出しモード。

    2026-07-07時点でSuno公式APIの一般公開エンドポイント・パラメータ・料金�は準備中のため、ズトーに口论しスのにススぉつちい 
    ここでは呼び出し部分を抽豱化し、実隙のHTTP実装にィーをヰ設定蝾
    仕様硺定後にプラグインする設計とする。

    環境変数 SUNO_API_KEY / SUNO_API_BASE_URL が未設定、ぽたは
    仕様硺定前は、明蚧なエラーメッセージを出して停止する
    (サイレント失敗・ダミー音源の混入を避けるため)。
    """

    ENV_API_KEY = "SUNO_API_KEY"
    ENV_BASE_URL = "SUNO_API_BASE_URL"

    def generate(self, project: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
        import os

        api_key = os.environ.get(self.ENV_API_KEY)
        base_url = os.environ.get(self.ENV_BASE_URL)

        if not api_key or not base_url:
            raise MusicProviderError(
                "Suno公式APIが未設定です。\n"
                f"  - 環境変数 {self.ENV_API_KEY} / {self.ENV_BASE_URL} が"
                " tools/mv-factory/.env に設定されていません。\n"
                "  - 2026-07-07時点でSuno公式APIの一般公開��様(�ンポポイント・"
                "パラメータ・料金)はオーナー確認待ちです。\n"
                "  - オーナーがAPIキー・仕様情報を入手し次第、"
                "mvfactory/providers/music.py の SunoApiProvider.generate() に"
                "実際のHTTP呼び出し(リクエスト整形・非同期ポーリング・"
                "音源ダウンロード)を実装してください。\n"
                "  - それまでは project.yaml の song_source を 'manual' にして、"
                "手持ち音源投入モードでパイプラインを進めてください。"
            )

        # --- ここから先はSuno公式API仕様確定後に実装する ---
        # 想定インターフェース(仕様確定後に確定させる):
        #   1. POST {base_url}/generate  (theme/lyrics_prompt/style_tags/instrumental送信)
        #   2. ジョブID取得 → GET {base_url}/status/{job_id} をポーリング
        #   3. 完了後、音源URLをダウンロードして out_dir/song.mp3 に保存
        #   4. 歌詞テキストをAPIレスポンスから取得し out_dir/lyrics.txt に保存
        #   5. song_meta.json にモデル名・生成日時・プロンプト・ジョブIDを記録
        raise MusicProviderError(
            "SunoApiProvider は仕様確定待ちのためHTTP呼び出し未実装です。"
            "上記のTODOコメントに沿って実装してください。"
        )


class SunoBridgeProvider(MusicProvider):
    """opensuno Bridge Mode(localhost:3001)経由でSuno公式アカウントから生成するモード。

    仕組み(実績: .agents/skills/suno-music-gen/scripts/suno_generate.py):
      Claude Code -> localhost:3001(bridge) -> WebSocket -> Chrome拡張
        -> suno.comログイン済みタブ(JWT自動取得) -> Suno公式内部API

    Suno公式パートナーAPI(SunoApiProvider)と異なり、これは自分のSunoアカウントの
    Web UIをブリッジ経由で叩く方式。追加課金なし(Sunoクレジットのみ消費)。

    1回の生成で2トラックが返る(Suno仕様)。本プロバイダは両方ダウンロードし、
    以下の基準で1本を選択する:
      1. 生成ステータスが complete のものを優先(streamingのみは除外)
      2. 尺(duration)が長い方を優先(MVの元素材としてより多くの区間を使えるため)
      3. 尺が同じ/取得できない場合は最初に complete になった方(リストの先頭)
    選ばれなかった方のトラックも `alt_song.mp3` として保存し、歌詞は
    `lyrics.txt` に加えて `song_meta.json` にも記録する。
    """

    BRIDGE = "http://localhost:3001"
    POLL_INTERVAL_SEC = 10
    POLL_TIMEOUT_SEC = 600

    def generate(self, project: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
        self._check_bridge()

        suno_cfg = project.get("suno_bridge") or project.get("suno_api") or {}
        theme = suno_cfg.get("theme") or project.get("theme") or ""
        lyrics_text = suno_cfg.get("lyrics") or ""
        lyrics_file = suno_cfg.get("lyrics_file")
        if not lyrics_text and lyrics_file:
            lyrics_path = Path(lyrics_file)
            if not lyrics_path.is_absolute():
                lyrics_path = out_dir / lyrics_path
            if lyrics_path.exists():
                lyrics_text = lyrics_path.read_text(encoding="utf-8")
        style_tags = suno_cfg.get("style_tags") or []
        style = ", ".join(style_tags) if style_tags else suno_cfg.get("style", "")
        title = suno_cfg.get("title") or project.get("title") or "untitled"
        instrumental = bool(suno_cfg.get("instrumental", False))
        model = suno_cfg.get("model", "chirp-crow")

        if not lyrics_text and not instrumental:
            raise MusicProviderError(
                "song_source=suno_bridge で instrumental=false の場合、"
                "suno_bridge.lyrics または suno_bridge.lyrics_file で歌詞を"
                "指定してください(project.yamlの該当フィールド)。"
            )

        log(f"Suno Bridge: カスタム生成開始 title={title!r} style={style!r}")
        payload = {
            "prompt": lyrics_text,
            "tags": style,
            "title": title,
            "make_instrumental": instrumental,
            "mv": model,
            "wait_audio": False,
        }
        resp = self._api("POST", "/api/custom_generate", payload)
        clips = self._as_clip_list(resp)
        if not clips:
            raise MusicProviderError(
                f"Suno Bridge: 生成開始レスポンスにクリップがありません: "
                f"{json.dumps(resp, ensure_ascii=False)[:500]}"
            )
        ids = [c["id"] for c in clips if c.get("id")]
        if not ids:
            raise MusicProviderError("Suno Bridge: クリップIDが取得できませんでした。")

        log(f"Suno Bridge: 生成ジョブ開始 ids={ids} (完了までポーリングします)")
        completed = self._poll(ids)

        out_dir.mkdir(parents=True, exist_ok=True)
        selected, alternates = self._select_best(completed)
        if selected is None:
            raise MusicProviderError(
                "Suno Bridge: 完了したクリップがありません(全てerrorまたはタイムアウト)。"
                f" 詳細: {json.dumps(completed, ensure_ascii=False)[:800]}"
            )

        dest_audio = out_dir / "song.mp3"
        self._download(selected["audio_url"], dest_audio)
        log(f"Suno Bridge: 選択トラックを保存しました: {dest_audio.name}")

        dest_lyrics = out_dir / "lyrics.txt"
        if lyrics_text:
            dest_lyrics.write_text(lyrics_text, encoding="utf-8")
        else:
            # instrumentalの場合、Sunoが生成したメタデータのタイトル等を記録するのみ
            dest_lyrics.write_text("", encoding="utf-8")

        alt_files = []
        for i, alt in enumerate(alternates):
            if not alt.get("audio_url"):
                continue
            alt_dest = out_dir / f"alt_song_{i+1}.mp3"
            try:
                self._download(alt["audio_url"], alt_dest)
                alt_files.append(alt_dest.name)
            except Exception as e:  # noqa: BLE001
                log(f"Suno Bridge: 代替トラックのダウンロードに失敗(無視して続行): {e}")

        meta = {
            "song_source": "suno_bridge",
            "title": selected.get("title") or title,
            "selected_id": selected.get("id"),
            "selected_duration_sec": self._duration_of(selected),
            "selection_reason": (
                "complete ステータスかつ尺が長い方を選択"
                "(同尺/不明の場合は先に完了した方)"
            ),
            "audio_file": dest_audio.name,
            "lyrics_file": dest_lyrics.name,
            "alternate_files": alt_files,
            "alternate_ids": [c.get("id") for c in alternates],
            "model": model,
            "style_tags": style_tags,
            "instrumental": instrumental,
            "copyright_note": (
                "Suno公式アカウント(opensuno Bridge経由)で生成した楽曲。"
                "商用利用可否はSuno社のサービス利用規約・加入プランに従う。"
                "収益化・公開前提で使う場合はオーナーの明示承認を得ること"
                "(要件定義書6章参照)。本モジュールはこの点を保証しない。"
            ),
        }
        write_json(out_dir / "song_meta.json", meta)
        return meta

    # --- internal helpers ---

    def _check_bridge(self) -> None:
        try:
            status = self._api("GET", "/api/status")
        except MusicProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise MusicProviderError(
                "Suno Bridge(localhost:3001)に接続できません。"
                "opensuno bridgeが起動しているか確認してください"
                "(launchctl kickstart -k gui/$(id -u)/com.ynfactory.opensuno-bridge)。"
                f" 詳細: {e}"
            ) from e
        if not status.get("connected"):
            raise MusicProviderError(
                "Suno Bridge: Chrome拡張が未接続です。"
                "suno.comのログイン済みタブを開いてください"
                "(拡張が有効か chrome://extensions でも確認してください)。"
            )

    def _api(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        url = f"{self.BRIDGE}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as e:
            raise MusicProviderError(f"Suno Bridge API呼び出し失敗 ({path}): {e}") from e

    @staticmethod
    def _as_clip_list(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            return data.get("clips", [])
        return data or []

    def _poll(self, ids: List[str]) -> List[Dict[str, Any]]:
        deadline = time.time() + self.POLL_TIMEOUT_SEC
        done: Dict[str, Dict[str, Any]] = {}
        ids_param = ",".join(ids)
        while time.time() < deadline and len(done) < len(ids):
            time.sleep(self.POLL_INTERVAL_SEC)
            clips = self._as_clip_list(self._api("GET", f"/api/get?ids={ids_param}"))
            for c in clips:
                cid = c.get("id")
                if not cid or cid in done:
                    continue
                status = c.get("status")
                if status == "complete" and c.get("audio_url"):
                    done[cid] = c
                elif status == "error":
                    done[cid] = c
            pending = [c.get("status") for c in clips if c.get("id") not in done]
            log(f"  Suno Bridge 待機中... 完了 {len(done)}/{len(ids)} (残り: {pending})")
        if len(done) < len(ids):
            log(f"Suno Bridge: タイムアウト({self.POLL_TIMEOUT_SEC}秒)。完了分のみで進行します。")
        return list(done.values())

    @staticmethod
    def _duration_of(clip: Dict[str, Any]) -> Optional[float]:
        meta = clip.get("metadata") or {}
        d = meta.get("duration")
        try:
            return float(d) if d is not None else None
        except (TypeError, ValueError):
            return None

    def _select_best(
        self, clips: List[Dict[str, Any]]
    ) -> "tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]":
        completed = [c for c in clips if c.get("status") == "complete" and c.get("audio_url")]
        if not completed:
            return None, []

        def sort_key(c: Dict[str, Any]) -> float:
            d = self._duration_of(c)
            return d if d is not None else -1.0

        ordered = sorted(completed, key=sort_key, reverse=True)
        return ordered[0], ordered[1:]

    def _download(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "mv-factory/0.1"})
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)


class ManualAudioProvider(MusicProvider):
    """手持ち音源投入モード。

    project.yaml の manual_audio.audio_path / manual_audio.lyrics_path を
    プロジェクトディレクトリ配下に正規化してコピーする。
    """

    def generate(self, project: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
        manual = project.get("manual_audio") or {}
        audio_rel = manual.get("audio_path")
        lyrics_rel = manual.get("lyrics_path")
        if not audio_rel or not lyrics_rel:
            raise MusicProviderError(
                "song_source=manual の場合、project.yaml の "
                "manual_audio.audio_path と manual_audio.lyrics_path が必須です。"
            )

        project_root = out_dir  # out_dir = プロジェクトディレクトリ直下
        audio_src = self._resolve(project_root, audio_rel)
        lyrics_src = self._resolve(project_root, lyrics_rel)

        if not audio_src.exists():
            raise MusicProviderError(f"音源ファイルが見つかりません: {audio_src}")
        if not lyrics_src.exists():
            raise MusicProviderError(f"歌詞ファイルが見つかりません: {lyrics_src}")

        ext = audio_src.suffix.lower()
        if ext not in (".mp3", ".wav")):
            raise MusicProviderError(
                f"音源ファイルはmp3/wavのみ対応です(実際: {ext})"
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        dest_audio = out_dir / f"song{ext}"
        dest_lyrics = out_dir / "lyrics.txt"
        shutil.copyfile(audio_src, dest_audio)
        shutil.copyfile(lyrics_src, dest_lyrics)
        log(f"手動ち音源を抭入しました: {dest_audio.name}")

        meta = {
            "song_source": "manual",
            "original_audio_path": str(audio_src),
            "original_lyrics_path": str(lyrics_src),
            "audio_file": dest_audio.name,
            "lyrics_file": dest_lyrics.name,
            "copyright_note": (
                "手持ち音源のため、商用利用另曁は音源の取得元ライセンスに依存する。"
                "本パイプラインはこの点を検証ヮ保証してください"
            ),
        }
        write_json(out_dir / "song_meta.json", meta)
        return meta

    @staticmethod
    def _resolve(project_root: Path, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return (project_root / p).resolve()


def get_provider(song_source: str) -> MusicProvider:
    if song_source == "suno_api":
        return SunoApiProvider()
    if song_source == "suno_bridge":
        return SunoBridgeProvider()
    if song_source == "manual":
        return ManualAudioProvider()
    raise MusicProviderError(f"未知の song_source です: {song_source!r}")
