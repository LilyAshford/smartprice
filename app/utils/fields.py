from wtforms import Field
from wtforms.widgets import TextInput

class ArrayField(Field):
    """
    A custom WTForms field for handling SQLAlchemy ARRAY columns.
    Renders as a text input where values are comma-separated.
    """
    widget = TextInput()

    def _value(self):
        if self.data:
            return ', '.join(self.data)
        return ''

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = [x.strip() for x in valuelist[0].split(',') if x.strip()]
        else:
            self.data = []