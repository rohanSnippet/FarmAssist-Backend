from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction # <-- Add this import
from django.core.cache import cache
from deep_translator import GoogleTranslator
import threading
from .models import Post

def translate_post_background(post_id):
    post = Post.objects.get(id=post_id)
    try:
        post.content_hi = GoogleTranslator(source='auto', target='hi').translate(post.content)
        post.content_mr = GoogleTranslator(source='auto', target='mr').translate(post.content)
        post.save(update_fields=['content_hi', 'content_mr'])
    except Exception as e:
        print(f"Translation failed: {e}")

@receiver(post_save, sender=Post)
def handle_new_post(sender, instance, created, **kwargs):
    if created:
        # 1. Trigger background translation
        threading.Thread(target=translate_post_background, args=(instance.id,)).start()
        
        # 2. Redis Cache Eviction (Clear stale feeds)
        transaction.on_commit(lambda: cache.delete("feed_page_1_All"))
        transaction.on_commit(lambda: cache.delete(f"feed_page_1_{instance.category}"))