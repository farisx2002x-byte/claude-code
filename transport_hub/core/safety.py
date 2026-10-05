"""فحوصات أمان المدخلات المرفوعة: حجم الملف، قنبلة الضغط في zip، وحد الصفوف في CSV."""

import io
import zipfile

MAX_FILE_MB = 1024
MAX_ZIP_UNCOMPRESSED_MB = 2048
MAX_ZIP_RATIO = 200
MAX_CSV_ROWS = 5_000_000


class UnsafeUpload(ValueError):
    """ملف مرفوع مرفوض لسبب أمني أو حجم، برسالة عربية."""


def check_size(size_bytes, max_mb=MAX_FILE_MB):
    if size_bytes > max_mb * 1e6:
        raise UnsafeUpload(f"حجم الملف {size_bytes / 1e6:.0f} MB يتجاوز الحد المسموح ({max_mb} MB)")


def check_zip(data):
    """يفحص zip دون فكه: عدد الملفات، الحجم بعد الفك، ونسبة الضغط، وأسماء المسارات الخطرة."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UnsafeUpload("الملف ليس zip صالحاً") from e
    infos = z.infolist()
    if len(infos) > 10_000:
        raise UnsafeUpload("عدد الملفات داخل zip كبير جداً")
    total = sum(i.file_size for i in infos)
    if total > MAX_ZIP_UNCOMPRESSED_MB * 1e6:
        raise UnsafeUpload(f"الحجم بعد الفك ({total / 1e6:.0f} MB) يتجاوز الحد")
    if len(data) and total / len(data) > MAX_ZIP_RATIO:
        raise UnsafeUpload("نسبة الضغط غير طبيعية (احتمال قنبلة ضغط)")
    for i in infos:
        if i.filename.startswith(("/", "\\")) or ".." in i.filename.replace("\\", "/").split("/"):
            raise UnsafeUpload(f"مسار غير آمن داخل zip: {i.filename}")


def check_csv_rows(df):
    if len(df) > MAX_CSV_ROWS:
        raise UnsafeUpload(f"عدد الصفوف {len(df):,} يتجاوز الحد ({MAX_CSV_ROWS:,})")
    return df
