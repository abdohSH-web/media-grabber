from pathlib import Path
from PIL import Image

# تحديد المجلد الذي يوجد فيه هذا السكريبت تلقائياً
script_dir = Path(__file__).resolve().parent

# أسماء الصور كما سميتها أنت
image_files = ['icon_16.png', 'icon_24.png', 'icon_32.png', 'icon_48.png', 'icon_64.png', 'icon_128.png', 'icon_256.png']

# فتح الصور باستخدام المسار النسبي لمكان السكريبت
images = [Image.open(script_dir / f) for f in image_files]

# حفظ ملف الـ ICO الناتج في نفس المجلد (أو يمكنك حفظه في المجلد الرئيسي)
output_ico = script_dir / 'icon.ico'
images[-1].save(
    output_ico,
    format='ICO',
    append_images=images[:-1]
)

print(f"✅ تم دمج جميع المقاسات بنجاح وحفظ الملف في: {output_ico}")