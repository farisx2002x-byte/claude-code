from src import load_data as L

SAMPLE = """<kml><Document><Placemark><name>طالب تجريبي</name><description><![CDATA[
<table><tr><td>رقم الطالب</td><td>123</td></tr><tr><td>المدرسة</td><td>ياسمين جدة</td></tr>
<tr><td>المرحلة</td><td>الابتدائية</td></tr><tr><td>ولي الأمر</td><td>فلان</td></tr>
<tr><td>الجوال</td><td>0500000000</td></tr><tr><td>العنوان</td><td>جدة</td></tr></table>]]></description>
<Point><coordinates>39.2,21.5,0</coordinates></Point></Placemark></Document></kml>"""


def test_parse_students():
    df = L.parse_students_kml(SAMPLE)
    assert len(df) == 1
    r = df.iloc[0]
    assert r.school == "ياسمين جدة" and r.stage == "ابتدائي" and r.sid == "123"
    assert 5e5 < r.x < 5.5e5


def test_stage_norm():
    assert L.norm_stage("الصفوف الاولية") == "ابتدائي"
    assert L.norm_stage("المتوسطة") == "متوسط"
    assert L.norm_stage("الثانوية") == "ثانوي"
    assert L.norm_stage("الطفولة المبكرة") == "طفولة مبكرة"


def test_lookup_manual_and_auto():
    lk = L.build_school_lookup(["ياسمين جدة", "مدرسة النور الأهلية"], ["ياسمين جدة النموذجية", "مدرسة النور الأهليه"])
    d = lk.set_index("student_school")
    assert d.loc["ياسمين جدة", "match"] == "manual"
    assert d.loc["مدرسة النور الأهلية", "official_name"] == "مدرسة النور الأهليه"
