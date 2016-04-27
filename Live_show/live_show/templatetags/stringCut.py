from django import template
register = template.Library()
def stringCut(string):
    lenLimit = 10
    str = string
    if len(string) > lenLimit:
        str = string[0:lenLimit] + '...'
    return str
register.filter(stringCut)