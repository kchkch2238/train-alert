"""
SRT / KTX 빈자리 텔레그램 알림 (명령어 제어 버전)
=====================================================
텔레그램에서 사용 가능한 명령어:
  /srt 수서 부산 20250405 08   → SRT 알림 시작
  /ktx 서울 부산 20250405 08   → KTX 알림 시작
  /stop                        → 알림 중지
  /status                      → 현재 상태 확인
"""

import os
import time
import requests
import threading
from datetime import datetime

# =============================================
# 환경변수 (Railway Variables에서 설정)
# =============================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")
INTERVAL  = int(os.environ.get("INTERVAL", "60"))

# =============================================
# 전역 상태
# =============================================
alert_thread = None
stop_flag = threading.Event()
current_config = {}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =============================================
# 텔레그램
# =============================================

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"[{now()}] 텔레그램 오류: {e}")


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        res = requests.get(url, params=params, timeout=35)
        return res.json().get("result", [])
    except Exception:
        return []


# =============================================
# 열차 조회
# =============================================

def check_srt(config):
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        session.get("https://etk.srail.kr/hpg/hra/01/selectScheduleList.do", timeout=10)

        url = "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do"
        data = {
            "dptRsStnCdNm": config["dep_station"],
            "arvRsStnCdNm": config["arr_station"],
            "dptDt": config["dep_date"],
            "dptTm": f"{config['dep_time']}0000",
            "psgNum": "1",
            "seatAttCd": "015",
            "arriveTime": "N",
            "stdrBasisCd": "1",
            "trnGpCd": "300",
        }

        res = session.post(url, data=data, timeout=15)
        return parse_table(res.text, "SRT")

    except Exception as e:
        print(f"[{now()}] SRT 조회 오류: {e}")
        return []


def check_ktx(config):
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.letskorail.com",
        })

        url = (
            "https://www.letskorail.com/ebizprd/EbizPrdTicketpr21100W.do"
            f"?gubun=1"
            f"&txtGoAbrdDt={config['dep_date']}"
            f"&txtGoStart={config['dep_station']}"
            f"&txtGoEnd={config['arr_station']}"
            f"&txtGoHour={config['dep_time']}0000"
            f"&radJobId=1&txtPsgFlicnt=1"
        )

        res = session.get(url, timeout=15)
        return parse_table(res.text, "KTX")

    except Exception as e:
        print(f"[{now()}] KTX 조회 오류: {e}")
        return []


def parse_table(html, train_type):
    from html.parser import HTMLParser

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.current_row = []
            self.current_cell = ""
            self.in_cell = False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.current_row = []
            elif tag in ("td", "th"):
                self.in_cell = True
                self.current_cell = ""

        def handle_endtag(self, tag):
            if tag == "tr" and self.current_row:
                self.rows.append(self.current_row)
                self.current_row = []
            elif tag in ("td", "th"):
                self.current_row.append(self.current_cell.strip())
                self.in_cell = False

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data.strip()

    parser = TableParser()
    parser.feed(html)

    available = []
    for row in parser.rows:
        if train_type == "SRT" and len(row) >= 6:
            train_no = row[2]
            dep_t = row[3]
            arr_t = row[4]
            seat_text = row[5]
            if "예약" in seat_text and "매진" not in seat_text:
                available.append(f"SRT {train_no}  {dep_t} → {arr_t}  [{seat_text}]")

        elif train_type == "KTX" and len(row) >= 5:
            t_type = row[0]
            dep_t = row[2]
            arr_t = row[3]
            seat_info = row[4]
            if "KTX" in t_type and "예약" in seat_info and "매진" not in seat_info:
                available.append(f"KTX  {dep_t} → {arr_t}  [{seat_info}]")

    return available


# =============================================
# 알림 스레드
# =============================================

def alert_worker(config):
    global stop_flag
    train_type = config["train_type"]
    notified = set()

    send_telegram(
        f"🚄 <b>{train_type} 빈자리 알림 시작!</b>\n"
        f"구간: {config['dep_station']} → {config['arr_station']}\n"
        f"날짜: {config['dep_date']}  {config['dep_time']}시 이후\n"
        f"검색 간격: {INTERVAL}초\n\n"
        f"중지하려면 /stop 입력"
    )

    while not stop_flag.is_set():
        print(f"[{now()}] 🔍 {train_type} 빈자리 조회 중...")

        if train_type == "SRT":
            available = check_srt(config)
        else:
            available = check_ktx(config)

        new_seats = [s for s in available if s not in notified]

        if new_seats:
            for seat in new_seats:
                link = "https://etk.srail.kr" if train_type == "SRT" else "https://www.letskorail.com"
                send_telegram(
                    f"🚨 <b>빈자리 발생!</b>\n\n"
                    f"{seat}\n\n"
                    f"⚡ 빨리 예약하세요!\n{link}"
                )
                print(f"[{now()}] ✅ 발견: {seat}")
                notified.add(seat)
        else:
            print(f"[{now()}] ❌ 빈자리 없음. {INTERVAL}초 후 재시도...")

        stop_flag.wait(INTERVAL)

    print(f"[{now()}] ⏹ 알림 종료")


# =============================================
# 명령어 처리
# =============================================

def handle_command(text: str):
    global alert_thread, stop_flag, current_config

    parts = text.strip().split()
    cmd = parts[0].lower()

    # /stop
    if cmd == "/stop":
        if alert_thread and alert_thread.is_alive():
            stop_flag.set()
            send_telegram("⏹ 알림을 중지했어요!")
        else:
            send_telegram("현재 실행 중인 알림이 없어요.")
        return

    # /status
    if cmd == "/status":
        if alert_thread and alert_thread.is_alive():
            send_telegram(
                f"✅ <b>알림 실행 중</b>\n"
                f"열차: {current_config.get('train_type')}\n"
                f"구간: {current_config.get('dep_station')} → {current_config.get('arr_station')}\n"
                f"날짜: {current_config.get('dep_date')}  {current_config.get('dep_time')}시 이후"
            )
        else:
            send_telegram("현재 실행 중인 알림이 없어요.\n\n사용법:\n/srt 수서 부산 20250405 08\n/ktx 서울 부산 20250405 08")
        return

    # /srt 또는 /ktx
    if cmd in ("/srt", "/ktx"):
        if len(parts) < 5:
            send_telegram(
                "⚠️ 입력 형식이 잘못됐어요!\n\n"
                "올바른 형식:\n"
                "/srt 출발역 도착역 날짜 시간\n\n"
                "예시:\n"
                "/srt 수서 부산 20250405 08\n"
                "/ktx 서울 부산 20250405 08"
            )
            return

        train_type = "SRT" if cmd == "/srt" else "KTX"
        dep_station = parts[1]
        arr_station = parts[2]
        dep_date    = parts[3]
        dep_time    = parts[4]

        # 날짜 형식 확인
        if len(dep_date) != 8 or not dep_date.isdigit():
            send_telegram("⚠️ 날짜는 YYYYMMDD 형식으로 입력해주세요!\n예: 20250405")
            return

        # 시간 형식 확인
        if len(dep_time) != 2 or not dep_time.isdigit():
            send_telegram("⚠️ 시간은 두 자리로 입력해주세요!\n예: 08, 13, 17")
            return

        # 기존 알림 중지
        if alert_thread and alert_thread.is_alive():
            stop_flag.set()
            alert_thread.join(timeout=3)

        # 새 알림 시작
        stop_flag = threading.Event()
        current_config = {
            "train_type": train_type,
            "dep_station": dep_station,
            "arr_station": arr_station,
            "dep_date": dep_date,
            "dep_time": dep_time,
        }

        alert_thread = threading.Thread(target=alert_worker, args=(current_config,), daemon=True)
        alert_thread.start()
        return

    # 알 수 없는 명령어
    send_telegram(
        "사용 가능한 명령어:\n\n"
        "/srt 출발역 도착역 날짜 시간\n"
        "/ktx 출발역 도착역 날짜 시간\n"
        "/stop  → 알림 중지\n"
        "/status → 현재 상태\n\n"
        "예시:\n"
        "/srt 수서 부산 20250405 08\n"
        "/ktx 서울 부산 20250405 08"
    )


# =============================================
# 메인 실행
# =============================================

def main():
    print("=" * 50)
    print("🚄 SRT/KTX 빈자리 알림 봇 시작")
    print("텔레그램에서 명령어를 입력하세요")
    print("=" * 50)

    send_telegram(
        "🤖 <b>빈자리 알림 봇 시작!</b>\n\n"
        "사용 가능한 명령어:\n"
        "/srt 출발역 도착역 날짜 시간\n"
        "/ktx 출발역 도착역 날짜 시간\n"
        "/stop → 알림 중지\n"
        "/status → 현재 상태\n\n"
        "예시:\n"
        "/srt 수서 부산 20250405 08\n"
        "/ktx 서울 부산 20250405 08"
    )

    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", "")
            chat_id = str(message.get("chat", {}).get("id", ""))

            # 본인 채팅만 처리
            if chat_id == str(CHAT_ID) and text.startswith("/"):
                print(f"[{now()}] 명령어 수신: {text}")
                handle_command(text)


if __name__ == "__main__":
    main()
