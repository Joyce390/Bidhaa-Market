from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, DecimalField, FileField,  SelectField, IntegerField, BooleanField
from wtforms.validators import Length, EqualTo, Email, DataRequired, ValidationError,  NumberRange, Optional, Regexp
from market.models import User
from flask_wtf.file import FileField, FileAllowed



class RegisterForm(FlaskForm):
    username = StringField(label='User Name:', validators=[Length(min=2, max=30), DataRequired()])
    email = StringField(label='Email:', validators=[Email(), DataRequired()])
    phone = StringField('Phone Number', validators=[Length(min=10, max=15)])  
    password1 = PasswordField(label='Password:', validators=[Length(min=6), DataRequired()])
    password2 = PasswordField(label='Confirm Password:', validators=[EqualTo('password1'), DataRequired()])
    submit = SubmitField(label='Create Account')
    
    def validate_username(self, username_to_check):
        user = User.query.filter_by(username=username_to_check.data).first()
        if user:
            raise ValidationError('Username already exists!')
        
    def validate_email_address(self, email_address_to_check):
        email = User.query.filter_by(email=email_to_check.data).first()
        if email:
            raise ValidationError("Email already exists. Please use a different email.")
    def validate_phone(self, phone_to_check):
        phone = User.query.filter_by(phone=phone_to_check.data).first()
        if phone:
            raise ValidationError('phone in use!')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    password = PasswordField(label='Password:', validators=[DataRequired()])
    submit = SubmitField(label='Sign in')

class PurchaseItemForm(FlaskForm):
    submit = SubmitField(label="Purchase Item")

class SellItemForm(FlaskForm):
    submit = SubmitField(label='Sell Item!')

class PurchaseForm(FlaskForm):
    submit = SubmitField(label="Confirm Purchase")



class AddItemForm(FlaskForm):
    name = StringField('Item Name', validators=[DataRequired(), Length(min=2, max=100)])
    price = DecimalField('Price', validators=[DataRequired()])
    category = SelectField('Category', choices=[('Fashion', 'Fashion'), ('Electronics', 'Electronics'), ('Sports', 'Sports'), ('Tools', 'Tools')], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired(), Length(min=10, max=500)])
    barcode = StringField('Barcode')  
    image = FileField('Upload Image')
    submit = SubmitField('Add Item')


class ItemForm(FlaskForm):
    name = StringField('Item Name', validators=[DataRequired(), Length(min=2, max=100)])
    price = DecimalField('Price', validators=[DataRequired(), NumberRange(min=0)], places=2)
    category = SelectField('Category', choices=[('Fashion', 'Fashion'), ('Electronics', 'Electronics'), ('Sports', 'Sports')], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Length(max=500)])
    image = FileField('Upload Image', validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Images only!')])
    submit = SubmitField('Add Item')


class EditItemForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    price = DecimalField('Price', validators=[DataRequired()])
    category = StringField('Category', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[DataRequired()])
    image = FileField('Image')  # FileField for image upload


class EditProfileForm(FlaskForm):
    phone = StringField('Phone Number', validators=[Optional(), Length(min=10, max=20)])
    submit = SubmitField('Save Changes')
    

class AdminSettingsForm(FlaskForm):
    site_name = StringField('Site Name', validators=[DataRequired()])
    site_email = StringField('Site Email', validators=[Email(), DataRequired()])
    site_phone = StringField('Contact Phone', validators=[DataRequired()])
    max_users = IntegerField('Max Users Allowed', validators=[DataRequired()])
    enable_registration = BooleanField('Enable User Registration')
    transaction_fee = IntegerField('Transaction Fee (%)', validators=[DataRequired()])
    payment_gateway = StringField('Payment Gateway', validators=[DataRequired()])
    theme_color = StringField('Theme Color', validators=[DataRequired()])
