"""NSE daily files (scripts/bhav_history.py): both formats parse to the same rows; saving is resumable. No network."""
import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bhav_history as B  # noqa: E402


def zipped(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


OLD = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n" \
      "ABC,EQ,10,11,9.5,10.5,10.4,10,1000,10500,03-JAN-2018,10,INE001,\nGB1,GB,1,1,1,1,1,1,1,1,03-JAN-2018,1,IN0,\nDEF,BE,20,20,20,20,20,19,5,100,03-JAN-2018,1,INE002,\n"
NEW = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n" \
      "2025-11-03,2025-11-03,CM,NSE,STK,1,INE001,ABC,EQ,,,,,ABC LTD,200,210,195,205,205,200,,205,,,3000,615000,40,F1,1,,,,,\n"


def test_both_formats_give_the_same_columns():
    a = B.parse(zipped("cm03JAN2018bhav.csv", OLD), date(2018, 1, 3))
    assert a == [["2018-01-03", "ABC", "EQ", 10.0, 11.0, 9.5, 10.5, 10.0, 1000, 10500.0, "INE001"], ["2018-01-03", "DEF", "BE", 20.0, 20.0, 20.0, 20.0, 19.0, 5, 100.0, "INE002"]]
    b = B.parse(zipped("BhavCopy_NSE_CM.csv", NEW), date(2025, 11, 3))
    assert b == [["2025-11-03", "ABC", "EQ", 200.0, 210.0, 195.0, 205.0, 200.0, 3000, 615000.0, "INE001"]]


def test_urls_switch_format_in_july_2024():
    assert B.url_for(date(2018, 1, 3)).endswith("/2018/JAN/cm03JAN2018bhav.csv.zip")
    assert B.url_for(date(2025, 11, 3)).endswith("BhavCopy_NSE_CM_0_0_0_20251103_F_0000.csv.zip")


def test_saving_is_resumable_and_holidays_are_remembered(tmp_path):
    calls = []
    def get(url):
        calls.append(url)
        if "04JAN2018" in url:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "no file", None, None)
        return zipped("x.csv", OLD)
    assert B.run(date(2018, 1, 3), date(2018, 1, 4), tmp_path, log=lambda *a: None, get=get) == 1
    n = len(calls)
    assert B.run(date(2018, 1, 3), date(2018, 1, 4), tmp_path, log=lambda *a: None, get=get) == 0 and len(calls) == n   # nothing fetched again
    assert len(B.load_all(tmp_path)) == 2
