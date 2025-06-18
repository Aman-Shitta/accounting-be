from django.contrib import admin

from document.models import *

# Register your models here.

admin.site.register(DimAICDocument)
admin.site.register(FactAICDocKeyItem)
admin.site.register(FactAICDocLine)
admin.site.register(FactAICDocLineItem)