"""
SRT / KTX 빈자리 텔레그램 알림 (Railway 클라우드용)
"""

import os
import time
import requests
from datetime import datetime

# =============================================
# 환경변수에서 설정값 불러오기 (Railway에서 설정)
# =============================================

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID     = os.environ.get("CHAT_ID", "")
TRAIN_TYPE  = os.environ.get("TRAIN_TYPE", "SRT")       # SRT 또는 KTX
DEP_STATION = os.environ.get("DEP_STATION", "수서")
ARR_STATION = os.environ.get("ARR_STATION", "부산")
DEP_DATE    = os.environ.get("DEP_DATE", "20250405")    # YYYYMMDD
DEP_TIME    = os.environ.get("DEP_TIME", "08")          # 00~23
INTERVAL    = int(os.environ.get("INTERVAL", "60"))     # 검색 간격 (초)

# =============================================
# 유틸리티
# =============================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def send_telegram(message: str):
    """텔레그램으로 메시지 전송"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        res = requests.post(url, data=data, timeout=10)
        if res.status_code == 200:
            print(f"[{now()}] 📱 텔레그램 전송 완료!")
        else:
            print(f"[{now()}] ⚠️ 전송 실패: {res.text}")
    except Exception as e:
        print(f"[{now()}] ⚠️ 오류: {e}")


# =============================================
# SRT 빈자리 확인
# =============================================

def check_srt():
    """SRT 빈자리 확인"""
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        # 먼저 메인 페이지 접속 (세션 쿠키 획득)
        session.get("https://etk.srail.kr/hpg/hra/01/selectScheduleList.do", timeout=10)

        url = "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do"
        data = {
            "dptRsStnCdNm": DEP_STATION,
            "arvRsStnCdNm": ARR_STATION,
            "dptDt": DEP_DATE,
            "dptTm": f"{DEP_TIME}0000",
            "psgNum": "1",
            "seatAttCd": "015",
            "arriveTime": "N",
            "stdrBasisCd": "1",
            "trnGpCd": "300",
        }

        res = session.post(url, data=data, timeout=15)
        available = []

        # 응답에서 빈자리 파싱
        from html.parser import HTMLParser

        class SRTParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_table = False
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

        parser = SRTParser()
        parser.feed(res.text)

        for row in parser.rows:
            if len(row) >= 6:
                seat_text = row[5]
                dep_t = row[3]
                arr_t = row[4]
                train_no = row[2]
                if "예약" in seat_text and "매진" not in seat_text:
                    available.append(f"SRT {train_no}  {dep_t} → {arr_t}  [{seat_text}]")

        return available

    except Exception as e:
        print(f"[{now()}] SRT 조회 오류: {e}")
        return []


# =============================================
# KTX 빈자리 확인
# =============================================

def check_ktx():
    """KTX 빈자리 확인"""
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.letskorail.com",
        })

        url = (
            "https://www.letskorail.com/ebizprd/EbizPrdTicketpr21100W.do"
            f"?gubun=1"
            f"&txtGoAbrdDt={DEP_DATE}"
            f"&txtGoStart={DEP_STATION}"
            f"&txtGoEnd={ARR_STATION}"
            f"&txtGoHour={DEP_TIME}0000"
            f"&radJobId=1&txtPsgFlicnt=1"
        )

        res = session.get(url, timeout=15)
        available = []

        from html.parser import HTMLParser

        class KTXParser(HTMLParser):
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

        parser = KTXParser()
        parser.feed(res.text)

        for row in parser.rows:
            if len(row) >= 5:
                train_type = row[0]
                dep_t = row[2]
                arr_t = row[3]
                seat_info = row[4]
                if "KTX" in train_type and "예약" in seat_info and "매진" not in seat_info:
                    available.append(f"KTX  {dep_t} → {arr_t}  [{seat_info}]")

        return available

    except Exception as e:
        print(f"[{now()}] KTX 조회 오류: {e}")
        return []


# =============================================
# 메인 실행
# =============================================

def main():
    print("=" * 50)
    print(f"🚄 {TRAIN_TYPE} 빈자리 알림 시작")
    print(f"   구간: {DEP_STATION} → {ARR_STATION}")
    print(f"   날짜: {DEP_DATE}  {DEP_TIME}시 이후")
    print(f"   검색 간격: {INTERVAL}초")
    print("=" * 50)

    send_telegram(
        f"🚄 <b>{TRAIN_TYPE} 빈자리 알림 시작</b>\n"
        f"구간: {DEP_STATION} → {ARR_STATION}\n"
        f"날짜: {DEP_DATE}  {DEP_TIME}시 이후\n"
        f"검색 간격: {INTERVAL}초"
    )

    notified = set()

    while True:
        print(f"[{now()}] 🔍 빈자리 조회 중...")

        if TRAIN_TYPE == "SRT":
            available = check_srt()
        else:
            available = check_ktx()

        new_seats = [s for s in available if s not in notified]

        if new_seats:
            for seat in new_seats:
                msg = (
                    f"🚨 <b>빈자리 발생!</b>\n\n"
                    f"{seat}\n\n"
                    f"⚡ 빨리 예약하세요!\n"
                    f"{'https://etk.srail.kr' if TRAIN_TYPE == 'SRT' else 'https://www.letskorail.com'}"
                )
                print(f"[{now()}] ✅ 발견: {seat}")
                send_telegram(msg)
                notified.add(seat)
        else:
            print(f"[{now()}] ❌ 빈자리 없음. {INTERVAL}초 후 재시도...")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
