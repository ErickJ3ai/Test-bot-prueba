# --- RECOMPENSAS, ADMIN, ACTUALIZACIÓN DE SALDO Y MISIONES ---
class RedeemMenuView(View):
    def __init__(self, items):
        super().__init__(timeout=300)
        self.items = items
        for i, (item_id, price, stock) in enumerate(self.items):
            robux_amount = item_id.split('_')[0]
            label = f"{robux_amount} ⏣ ({price} LBucks)"
            button = Button(label=label, custom_id=f"redeem_{item_id}", style=discord.ButtonStyle.blurple, disabled=(stock <= 0))
            button.callback = self.handle_redeem_click
            self.add_item(button)

    async def handle_redeem_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        custom_id = interaction.data['custom_id']
        item_id = custom_id.replace("redeem_", "")
        item = await asyncio.to_thread(db.get_item, item_id)
        if not item:
            return await interaction.followup.send("Este item ya no existe.", ephemeral=True)
        view = ConfirmCancelView(user_id=interaction.user.id, item_id=item_id, price=item[1])
        await interaction.followup.send(f"¿Confirmas canje de **{item[0].split('_')[0]} Robux** por **{item[1]} LBucks**?", view=view, ephemeral=True)

class ConfirmCancelView(View):
    def __init__(self, user_id, item_id, price):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.item_id = item_id
        self.price = price

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success)
    async def confirm_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        balance = await asyncio.to_thread(db.get_balance, self.user_id)
        item_data = await asyncio.to_thread(db.get_item, self.item_id)
        if not item_data or item_data[2] <= 0:
            await interaction.followup.send("¡Se agotó el item!", ephemeral=True)
            return
        if balance < self.price:
            await interaction.followup.send("No tienes suficientes LBucks.", ephemeral=True)
            return
        await asyncio.to_thread(db.update_lbucks, self.user_id, -self.price)
        await asyncio.to_thread(db.update_stock, self.item_id, -1)
        log_channel = bot.get_channel(REDEMPTION_LOG_CHANNEL_ID)
        if log_channel:
            robux_amount = self.item_id.split('_')[0]
            embed = discord.Embed(title="⏳ Nuevo Canjeo Pendiente",
                                  description=f"Usuario **{interaction.user.name}** ({interaction.user.id}) canjeó **{robux_amount} Robux**",
                                  color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            log_message = await log_channel.send(embed=embed, view=AdminActionView())
            await asyncio.to_thread(db.create_redemption, self.user_id, self.item_id, log_message.id)
        await interaction.followup.send("¡Canjeo realizado! Un admin lo revisará.", ephemeral=True)
        await interaction.edit_original_response(content="Procesando...", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Canje cancelado.", view=None)

class AdminActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Completar", style=discord.ButtonStyle.success, custom_id="persistent:admin_complete")
    async def complete_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.", ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)
        await asyncio.to_thread(db.update_redemption_status, redemption[0], 'completed')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(f"✅ Tu canjeo de **{item_name}** ha sido completado!")
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "✅ Canjeo Completado"
        edited_embed.color = discord.Color.green()
        edited_embed.add_field(name="Procesado por", value=interaction.user.mention, inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="persistent:admin_cancel")
    async def cancel_button(self, button: Button, interaction: discord.Interaction):
        await interaction.response.defer()
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if not admin_role or admin_role not in interaction.user.roles:
            return await interaction.followup.send("No tienes permiso.", ephemeral=True)
        redemption = await asyncio.to_thread(db.get_redemption_by_message, interaction.message.id)
        if not redemption or redemption[4] != 'pending':
            return await interaction.edit_original_response(content="Este canjeo ya fue procesado.", view=None, embed=None)
        item = await asyncio.to_thread(db.get_item, redemption[2])
        if item:
            await asyncio.to_thread(db.update_lbucks, redemption[1], item[1])
            await asyncio.to_thread(db.update_stock, redemption[2], 1)
        await asyncio.to_thread(db.update_redemption_status, redemption[0], 'cancelled_by_admin')
        user = await bot.fetch_user(redemption[1])
        item_name = redemption[2].split('_')[0] + " Robux"
        try:
            await user.send(f"❌ Tu canjeo de **{item_name}** fue cancelado. Tus LBucks fueron devueltos.")
        except discord.Forbidden:
            pass
        edited_embed = interaction.message.embeds[0]
        edited_embed.title = "❌ Canjeo Cancelado por Admin"
        edited_embed.color = discord.Color.dark_grey()
        edited_embed.add_field(name="Cancelado por", value=interaction.user.mention, inline=False)
        await interaction.edit_original_response(embed=edited_embed, view=None)

class UpdateBalanceView(View):
    def __init__(self):
        super().__init__(timeout=300)
    @discord.ui.button(label="🔄 Actualizar Saldo", style=discord.ButtonStyle.blurple, custom_id="update:balance")
    async def update_balance_button(self, button: Button, interaction: discord.Interaction):
        balance = await asyncio.to_thread(db.get_balance, interaction.user.id)
        await interaction.response.edit_message(content=f"Tu saldo actual es: **{balance} LBucks** 🪙", view=self)

class UpdateMissionsView(View):
    def __init__(self):
        super().__init__(timeout=300)
    @discord.ui.button(label="🔄 Actualizar Misiones", style=discord.ButtonStyle.blurple, custom_id="update:missions")
    async def update_missions_button(self, button: Button, interaction: discord.Interaction):
        missions = await asyncio.to_thread(db.get_daily_missions, interaction.user.id)
        if not missions:
            await interaction.response.send_message("No hay misiones disponibles.", ephemeral=True)
            return
        embed = discord.Embed(title="📝 Tus Misiones Diarias", description="Completa estas misiones para ganar LBucks.", color=discord.Color.blue())
        for m in missions:
            status_emoji = "✅" if m['is_completed'] else "⌛"
            progress_text = f"({m['progress']}/{m['target_value']})" if not m['is_completed'] else ""
            embed.add_field(name=f"{status_emoji} {m['description']}", value=f"Recompensa: **{m['reward']} LBucks** {progress_text}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)
