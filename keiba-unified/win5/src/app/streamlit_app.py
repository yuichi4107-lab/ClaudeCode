"""Streamlit Webダッシュボード"""

import sys
from datetime import date, timedelta
from pathlib import Path

# srcをパスに追加
src_dir = str(Path(__file__).resolve().parent.parent)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Win5 Predictor", page_icon="🏇", layout="wide")


def main():
    st.title("🏇 Win5 Predictor Dashboard")

    menu = st.sidebar.selectbox(
        "メニュー",
        ["システム状態", "Win5予測", "バックテスト", "モデル管理", "データ収集"],
    )

    if menu == "システム状態":
        page_status()
    elif menu == "Win5予測":
        page_predict()
    elif menu == "バックテスト":
        page_backtest()
    elif menu == "モデル管理":
        page_model()
    elif menu == "データ収集":
        page_collect()


def page_status():
    st.header("システム状態")

    from app.workflow import get_system_status
    status = get_system_status()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("レース数", f"{status['races_count']:,}")
    with col2:
        st.metric("結果レコード数", f"{status['results_count']:,}")
    with col3:
        model = status.get("active_model")
        if model:
            st.metric("モデル AUC", f"{model['auc']:.4f}")
        else:
            st.metric("モデル AUC", "N/A")

    st.subheader("詳細")
    st.json(status)


def page_predict():
    st.header("Win5 予測")

    col1, col2 = st.columns(2)
    with col1:
        target_date = st.date_input("対象日", value=date.today() + timedelta(days=(6 - date.today().weekday()) % 7))
    with col2:
        budget = st.number_input("予算 (円)", value=10000, step=1000, min_value=100)

    if st.button("予測実行", type="primary"):
        with st.spinner("予測中..."):
            try:
                from app.workflow import predict_win5
                result = predict_win5(target_date, budget=int(budget))

                st.success("予測完了!")

                # レース別予測結果
                for i, (race_id, pred_df) in enumerate(result["predictions"].items(), 1):
                    st.subheader(f"Race {i}: {race_id}")
                    if not pred_df.empty:
                        display_cols = [c for c in ["rank", "horse_number", "horse_name", "calibrated_prob"] if c in pred_df.columns]
                        st.dataframe(pred_df[display_cols].head(5), use_container_width=True)

                # チケット情報
                if result["ticket"]:
                    st.subheader("推奨買い目")
                    ticket = result["ticket"]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("組合せ数", ticket.num_combinations)
                    c2.metric("購入金額", f"¥{ticket.total_cost:,}")
                    c3.metric("的中確率", f"{ticket.total_hit_probability:.4%}")

                # レポート
                st.subheader("レポート")
                st.text(result["report"])

            except Exception as e:
                st.error(f"エラー: {e}")


def page_backtest():
    st.header("バックテスト")

    col1, col2, col3 = st.columns(3)
    with col1:
        start = st.date_input("開始日", value=date(2023, 1, 1), key="bt_start")
    with col2:
        end = st.date_input("終了日", value=date(2025, 12, 31), key="bt_end")
    with col3:
        budget = st.number_input("予算 (円)", value=10000, step=1000, min_value=100, key="bt_budget")

    if st.button("バックテスト実行", type="primary"):
        with st.spinner("バックテスト実行中..."):
            try:
                from app.workflow import run_backtest
                result = run_backtest(start, end, budget=int(budget))

                if result["results"].empty:
                    st.warning("バックテスト結果がありません")
                    return

                # サマリー
                roi = result["roi"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("ROI", f"{roi['roi']:.1f}%")
                c2.metric("損益", f"¥{roi['profit']:,.0f}")
                c3.metric("投資総額", f"¥{roi['total_cost']:,.0f}")
                c4.metric("配当総額", f"¥{roi['total_payout']:,.0f}")

                # グラフ
                from analysis.visualizer import Visualizer
                from analysis.roi_calculator import ROICalculator

                roi_calc = ROICalculator(result["results"])
                cumulative = roi_calc.cumulative_profit()
                if not cumulative.empty:
                    st.subheader("累計損益推移")
                    st.line_chart(cumulative.set_index("event_date")["cumulative_profit"])

                # レポート
                st.subheader("レポート")
                st.text(result.get("report", ""))

            except Exception as e:
                st.error(f"エラー: {e}")


def page_model():
    st.header("モデル管理")

    from model.registry import ModelRegistry
    registry = ModelRegistry()

    models = registry.list_models()
    if models:
        st.dataframe(pd.DataFrame(models), use_container_width=True)
    else:
        st.info("登録済みモデルはありません")

    st.subheader("新規モデル学習")
    col1, col2 = st.columns(2)
    with col1:
        train_start = st.date_input("学習開始日", value=date(2020, 1, 1), key="tr_start")
    with col2:
        train_end = st.date_input("学習終了日", value=date(2024, 12, 31), key="tr_end")

    optimize = st.checkbox("Optunaでハイパラ最適化")

    if st.button("学習開始", type="primary"):
        with st.spinner("モデル学習中..."):
            try:
                from app.workflow import train_model
                model_id = train_model(
                    train_start, train_end, optimize_hyperparams=optimize
                )
                st.success(f"学習完了: {model_id}")
            except Exception as e:
                st.error(f"エラー: {e}")


def page_collect():
    st.header("データ収集")

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("開始日", value=date(2020, 1, 1), key="col_start")
    with col2:
        end = st.date_input("終了日", value=date.today(), key="col_end")

    profiles = st.checkbox("馬・騎手プロフィールも収集", value=True)

    if st.button("収集開始", type="primary"):
        with st.spinner("データ収集中...（長時間かかります）"):
            try:
                from app.workflow import collect_data
                collect_data(start, end, profiles=profiles)
                st.success("データ収集完了!")
            except Exception as e:
                st.error(f"エラー: {e}")


if __name__ == "__main__":
    main()
