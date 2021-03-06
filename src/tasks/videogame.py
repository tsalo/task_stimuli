import os, sys, time, queue
import numpy as np
import threading

from psychopy import visual, core, data, logging, event, sound, constants
from .task_base import Task

from ..shared import config

import retro

DEFAULT_GAME_NAME = 'ShinobiIIIReturnOfTheNinjaMaster-Genesis'

#KEY_SET = 'zx__abudlr_y'
#KEY_SET = 'zx__udlry___'
#KEY_SET = ['a','b','c','d','up','down','left','right','x','y','z','k']
#KEY_SET = ['x','z','_','_','up','down','left','right','c','_','_','_']
KEY_SET = ['y','a','_','_','u','d','l','r','b','_','_','_']

#KEY_SET = '0123456789'

_keyPressBuffer = []
_keyReleaseBuffer = []
import pyglet

def _onPygletKeyPress(symbol, modifier):
    if modifier:
        event._onPygletKey(symbol, modifier)
    global _keyPressBuffer
    keyTime = core.getTime()
    key = pyglet.window.key.symbol_string(symbol).lower().lstrip('_').lstrip('NUM_')
    _keyPressBuffer.append((key, keyTime))

def _onPygletKeyRelease(symbol, modifier):
    global _keyReleaseBuffer
    keyTime = core.getTime()
    key = pyglet.window.key.symbol_string(symbol).lower().lstrip('_').lstrip('NUM_')
    _keyReleaseBuffer.append((key, keyTime))

class SoundDeviceBlockStream(sound.backend_sounddevice.SoundDeviceSound):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocks = queue.Queue()
        self.lock = threading.Lock()

    def add_block(self, block):
        with self.lock:
            self.blocks.put(block)

    def _nextBlock(self):
        if self.status == constants.STOPPED:
            return
        if self.blocks.empty():
            block = np.zeros((self.blockSize,2),dtype=np.float)
        else:
            with self.lock:
                block = self.blocks.get()
        self.t += self.blockSize/float(self.sampleRate)
        return block

class VideoGameBase(Task):

    def _render_graphics_sound(self, obs, sound_block, exp_win, ctl_win):
        self.game_vis_stim.image = np.flip(obs,0)/255.
        self.game_vis_stim.draw(exp_win)
        if ctl_win:
            self.game_vis_stim.draw(ctl_win)
        self.game_sound.add_block(sound_block[:735]/float(2**15))
        if not self.game_sound.status == constants.PLAYING:
            self.game_sound.play()

    def stop(self):
        self.game_sound.stop()

    def unload(self):
        self.emulator.close()

class VideoGame(VideoGameBase):

    DEFAULT_INSTRUCTION = "Let's play a video game.\n%s : %s\nHave fun!"

    def __init__(self,
        game_name=DEFAULT_GAME_NAME,
        state_name=None,
        scenario=None,
        repeat_scenario=True,
        max_duration=0,
        *args,**kwargs):

        super().__init__(**kwargs)
        self.game_name = game_name
        self.state_name = state_name
        self.scenario = scenario
        self.repeat_scenario = repeat_scenario
        self.max_duration = max_duration
        self.instruction = self.instruction%(self.game_name, self.state_name)

    def instructions(self, exp_win, ctl_win):

        screen_text = visual.TextStim(
            exp_win, text=self.instruction,
            alignHoriz="center", color = 'white', wrapWidth=config.WRAP_WIDTH)

        for frameN in range(config.FRAME_RATE * config.INSTRUCTION_DURATION):
            screen_text.draw(exp_win)
            if ctl_win:
                screen_text.draw(ctl_win)
            yield

    def _setup(self, exp_win):

        self.emulator = retro.make(
            self.game_name,
            state=self.state_name,
            scenario=self.scenario,
            record=False)

        self.game_vis_stim = visual.ImageStim(exp_win,size=exp_win.size,units='pixels',autoLog=False)
        self.game_sound = SoundDeviceBlockStream(stereo=True, blockSize=735)

    def _run(self, exp_win, ctl_win):
        global _keyReleaseBuffer, _keyPressBuffer
        # activate repeat keys
        exp_win.winHandle.on_key_press = _onPygletKeyPress
        exp_win.winHandle.on_key_release = _onPygletKeyRelease
        if ctl_win:
            ctl_win.winHandle.on_key_press = _onPygletKeyPress
            ctl_win.winHandle.on_key_release = _onPygletKeyRelease
        keys = [False]*12


        while True:
            self.emulator.reset()
            nnn = 0
            while True:
                movie_path = os.path.join(
                    self.output_path,
                    "%s_%s_%s_%03d.bk2"%(self.output_fname_base,self.game_name,self.state_name, nnn))
                if not os.path.exists(movie_path):
                    break
                nnn += 1
            logging.exp('VideoGame: recording movie in %s'%movie_path)
            self.emulator.record_movie(movie_path)

            total_reward = 0
            exp_win.logOnFlip(
                level=logging.EXP,
                msg='VideoGame %s: %s starting at %f'%(self.game_name, self.state_name, time.time()))
            while True:
                # TODO: get real action from controller
                #gamectrl_keys = event.getKeys(list(KEY_SET))
                #keys = [k in gamectrl_keys for k in KEY_SET]
                for k in _keyReleaseBuffer:
                    #print('release',k)
                    if k[0] in KEY_SET:
                        keys[KEY_SET.index(k[0])] = False
                _keyReleaseBuffer.clear()
                for k in _keyPressBuffer:
                    #print('press',k)
                    if k[0] in KEY_SET:
                        keys[KEY_SET.index(k[0])] = True
                _keyPressBuffer.clear()

                _obs, _rew, _done, _info = self.emulator.step(keys)
                total_reward += _rew
                if _rew > 0 :
                    exp_win.logOnFlip(level=logging.EXP, msg='Reward %f'%(total_reward))
                self._render_graphics_sound(_obs,self.emulator.em.get_audio(),exp_win, ctl_win)
                yield
                if _done:
                    break

            if not self.repeat_scenario or \
                (self.max_duration and
                self.task_timer.getTime() > self.max_duration): # stop if we are above the planned duration
                break
        # deactivate custom keys handling
        exp_win.winHandle.on_key_press = event._onPygletKey
        del exp_win.winHandle.on_key_release
        if ctl_win:
            ctl_win.winHandle.on_key_press = event._onPygletKey
            del ctl_win.winHandle.on_key_release

class VideoGameReplay(VideoGameBase):

    def __init__(self, movie_filename, game_name=DEFAULT_GAME_NAME, scenario=None, *args, **kwargs):
        super().__init__(**kwargs)
        self.game_name = game_name
        self.scenario = scenario
        self.movie_filename = movie_filename
        if not os.path.exists(self.movie_filename):
            raise ValueError('file %s does not exists'%self.movie_filename)

    def instructions(self, exp_win, ctl_win):
        instruction_text = "You are going to watch someone play %s."%self.game_name
        screen_text = visual.TextStim(
            exp_win, text=instruction_text,
            alignHoriz="center", color = 'white')

        for frameN in range(config.FRAME_RATE * INSTRUCTION_DURATION):
            screen_text.draw(exp_win)
            if ctl_win:
                screen_text.draw(ctl_win)
            yield

    def setup(self, exp_win, output_path, output_fname_base):
        super().setup(exp_win, output_path, output_fname_base)
        self.movie = retro.Movie(self.movie_filename)
        self.emulator = retro.make(
            self.game_name,
            record=False,
            state=retro.State.NONE,
            scenario=self.scenario,
            #use_restricted_actions=retro.Actions.ALL,
            players=self.movie.players)
        self.emulator.initial_state = self.movie.get_state()
        self.emulator.reset()

        self.game_vis_stim = visual.ImageStim(exp_win,size=exp_win.size,units='pixels',autoLog=False)
        self.game_sound = SoundDeviceBlockStream(stereo=True, blockSize=735)

    def _run(self, exp_win, ctl_win):
        # give the original size of the movie in pixels:
        #print(self.movie_stim.format.width, self.movie_stim.format.height)
        total_reward = 0
        exp_win.logOnFlip(
            level=logging.EXP,
            msg='VideoGameReplay %s starting at %f'%(self.game_name, time.time()))
        while self.movie.step():
            keys = []
            for p in range(self.movie.players):
                for i in range(self.emulator.num_buttons):
                    keys.append(self.movie.get_key(i, p))

            _obs, _rew, _done, _info = self.emulator.step(keys)

            total_reward += _rew
            if _rew > 0 :
                exp_win.logOnFlip(level=logging.EXP, msg='Reward %f'%(total_reward))

            self._render_graphics_sound(_obs,self.emulator.em.get_audio(), exp_win, ctl_win)
            yield
