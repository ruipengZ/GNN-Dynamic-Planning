import pybullet as p
import numpy as np

class Env:
    def __init__(self, cfg, GUI=False):
        try:
            p.disconnect()
        except:
            pass
        if GUI:
            p.connect(p.GUI, options='--background_color_red=0.97 --background_color_green=0.97 --background_color_blue=1.0')
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
            p.resetDebugVisualizerCamera(2., 50, -20, (0.5, 0.5, 0.5))
        else:
            p.connect(p.DIRECT)
        p.setGravity(0, 0, -10)
        self.config_dim = cfg['env']['config_dim']
        self.workspace_dim = cfg['env']['workspace_dim']
        self.arm_file_mine = cfg['env']['arm_file']
        self.arm_file_obs = cfg['env']['arm_file']
        self.arm_mine_base_pos = cfg['env']['arm_mine_base_pos']
        self.arm_mine_base_ori = cfg['env']['arm_mine_base_ori']
        self.arm_obs_1_base_pos = cfg['env']['arm_obs_1_base_pos']
        self.arm_obs_1_base_ori = cfg['env']['arm_obs_1_base_ori']
        self.arm_obs_2_base_pos = cfg['env']['arm_obs_2_base_pos']
        self.arm_obs_2_base_ori = cfg['env']['arm_obs_2_base_ori']

        self.create_env()
        self.episode_i = 0
        self.speed = 1 / (cfg['env']['unit_timestep'] - 1)
        self.CC_EPS = cfg['env']['CC_EPS']
        self.RRT_EPS = cfg['env']['RRT_EPS']
        self.collision_check_count = 0
        self.end_effector_index = 2


    def init_new_problem(self, file=None, index=None, setting_dict=None):
        self.create_env()
        # when training
        if file:
            with np.load(file) as f:
                self.init_states = f['init_states']
                self.goal_states = f['goal_states']
                self.obs_poss = f['obs_pos']
                self.obs_oris = f['obs_ori']
                self.obs_trajs = f['obs_traj']

        elif setting_dict:
            self.init_states = setting_dict['init_states']
            self.goal_states = setting_dict['goal_states']
            self.obs_poss = setting_dict['obs_pos']
            self.obs_oris = setting_dict['obs_ori']
            self.obs_trajs = setting_dict['obs_traj']

        else:
            raise RuntimeError('Error environment input')

        self.order = list(range(self.init_states.shape[0]))

        if index is None:
            index = self.episode_i

        self.init_state = self.init_states[self.order[index]]
        self.goal_state = self.goal_states[self.order[index]]

        # reset the obs base and orientation
        self.obs_pos = self.obs_poss[self.order[index]]
        self.obs_ori = self.obs_oris[self.order[index]]
        self.resetBaseOrientation(self.obs_pos, self.obs_ori)

        # obs_traj
        self.obs_traj = self.obs_trajs[self.order[index]]

        # get workspace points for traj
        self.obs_points = np.array([self.get_workspace_points(c) for c in self.obs_traj]).reshape(-1,self.workspace_dim)

        self.episode_i += 1
        self.episode_i = (self.episode_i) % len(self.order)
        self.collision_check_count = 0

    def create_env(self):
        p.resetSimulation()
        stick_mine = p.loadURDF(self.arm_file_mine, self.arm_mine_base_pos, self.arm_mine_base_ori, useFixedBase=True)
        stick_obs_1 = p.loadURDF(self.arm_file_obs, self.arm_obs_1_base_pos, self.arm_obs_1_base_ori, useFixedBase=True)
        stick_obs_2 = p.loadURDF(self.arm_file_obs, self.arm_obs_2_base_pos, self.arm_obs_2_base_ori, useFixedBase=True)
        self.stick_mine, self.stick_obs_1, self.stick_obs_2 = stick_mine, stick_obs_1, stick_obs_2


    def create_voxel(self, halfExtents, basePosition):
        groundColId = p.createCollisionShape(p.GEOM_BOX, halfExtents=halfExtents)
        groundVisID = p.createVisualShape(shapeType=p.GEOM_BOX,
                                          rgbaColor=np.random.uniform(0, 1, size=3).tolist() + [0.8],
                                          specularColor=[0.4, .4, 0],
                                          halfExtents=halfExtents)
        groundId = p.createMultiBody(baseMass=0,
                                     baseCollisionShapeIndex=groundColId,
                                     baseVisualShapeIndex=groundVisID,
                                     basePosition=basePosition)
        return groundId

    def resetBaseOrientation(self, base, orientation):
        p.resetBasePositionAndOrientation(self.stick_obs_1, base[:3], orientation[:4])
        p.resetBasePositionAndOrientation(self.stick_obs_2, base[3:], orientation[4:])

    def uniform_sample_mine(self, n=1):

        sample = np.random.uniform([0.] * self.config_dim, [np.pi] * self.config_dim, size=(n, self.config_dim))
        if n == 1:
            return sample.reshape(-1)
        else:
            return sample

    def uniform_sample_mine_wo_collision(self, n=1):

        samples = []
        count = 0
        while True:
            if count > 100000:
                return False
            if len(samples) == n:
                break
            sample = np.random.uniform([0.] * self.config_dim, [np.pi] * self.config_dim)
            self.set_config_mine(sample)
            if self.check_collision():
                samples.append(sample)
            else:
                count += 1

        return np.array(samples)

    def uniform_sample_obs(self, n=1):
        '''
        Uniformlly sample in the configuration space
        '''
        sample = np.random.uniform([0.] * self.config_dim, [np.pi] * self.config_dim, size=(n, self.config_dim))
        if n == 1:
            return sample.reshape(-1)
        else:
            return sample

    def set_config_mine(self, config):
        for i in range(len(config)):
            p.resetJointState(self.stick_mine, i, config[i])

    def set_config_obs(self, config):
        config_obs_1 = config[:self.config_dim]
        config_obs_2 = config[self.config_dim:]
        for i in range(len(config_obs_1)):
            p.resetJointState(self.stick_obs_1, i, config_obs_1[i])
            p.resetJointState(self.stick_obs_2, i, config_obs_2[i])

    def set_config_2arm(self, config, arm_id1, arm_id2):
        config_obs_1 = config[:self.config_dim]
        config_obs_2 = config[self.config_dim:]
        for i in range(len(config_obs_1)):
            p.resetJointState(arm_id1, i, config_obs_1[i])
            p.resetJointState(arm_id2, i, config_obs_2[i])

    def set_config_arm(self, config, arm_id):
        for i in range(len(config)):
            p.resetJointState(arm_id, i, config[i])


    def check_collision(self):
        p.performCollisionDetection()
        if len(p.getContactPoints(self.stick_mine)) == 0:
            return True
        else:
            return False

    def check_collision_body(self, body_id):
        p.performCollisionDetection()
        if len(p.getContactPoints(body_id)) == 0:
            return True
        else:
            return False

    def check_traj_collision_body(self, obs_traj, body_id):

        obs_traj_1 = obs_traj[:, :self.config_dim]
        obs_traj_2 = obs_traj[:, self.config_dim:]

        u_d = self.speed
        if not self.check_collision_body(body_id):
            return False

        interval_disp = obs_traj_1[1] - obs_traj_1[0]
        d = np.linalg.norm(interval_disp)
        K = int(np.ceil(d / u_d))

        for i in range(len(obs_traj_1) - 1):
            for k in range(1, K + 1):
                config_obs_1 = obs_traj_1[i] + k * 1. / K * interval_disp
                config_obs_2 = obs_traj_2[i] + k * 1. / K * interval_disp
                self.set_config_obs(np.array([config_obs_1, config_obs_2]).flatten())

                if not self.check_collision_body(body_id):
                    return False

        return True

    def get_workspace_points(self, obsconfig, relative=False):
        points = []
        self.set_config_obs(obsconfig)

        for effector in range(self.config_dim+1):
            point = p.getLinkState(self.stick_obs_1, effector)[0]
            point = (point[0], point[1], point[2])
            points.append(point)

        for effector in range(self.config_dim+1):
            point = p.getLinkState(self.stick_obs_2, effector)[0]
            point = (point[0], point[1], point[2])
            points.append(point)

        return np.array(points).reshape((-1))

    def get_workspace_points_mine(self, mineconfig, relative=False):
        points = []
        self.set_config_mine(mineconfig)
        for effector in range(3):
            point = p.getLinkState(self.stick_mine, effector)[0]
            point = (point[0], point[1], point[2])
            points.append(point)
        return np.array(points).reshape((-1))


    def _state_fp(self, mineconfig):
        self.set_config_mine(mineconfig)
        return self.check_collision()

    def _edge_fp(self, state, new_state, cur_time):
        assert state.size == new_state.size
        self.collision_check_count += 1

        disp_mine = new_state - state

        d = np.linalg.norm(disp_mine)
        K = int(np.ceil(d / self.speed))

        if d == 0:
            K=1



        # start
        self.set_config_mine(state)
        self.set_config_obs(self.obs_traj[min(int(cur_time), self.obs_points.shape[0] - 1)])
        if not self.check_collision():
            return False

        # mine moving
        self.collision_check_count += d // self.CC_EPS
        for k in range(1, K + 1):
            c_mine = state + k * 1. / K * disp_mine
            self.set_config_mine(c_mine)

            c_obs = self.obs_traj[min(int(cur_time) + k, self.obs_points.shape[0] - 1)]
            self.set_config_obs(c_obs)

            if not self.check_collision():
                return False

        return True


    def distance(self, from_state, to_state):
        '''
        Distance metric
        '''

        # to_state = np.maximum(to_state, np.array(self.pose_range)[:, 0])
        # to_state = np.minimum(to_state, np.array(self.pose_range)[:, 1])
        diff = np.abs(to_state - from_state)

        return np.sqrt(np.sum(diff ** 2, axis=-1))

    def in_goal_region(self, state):
        '''
        Return whether a state(configuration) is in the goal region
        '''
        return self.distance(state, self.goal_state) < self.RRT_EPS and \
               self._state_fp(state)


    #### For RL training ####
    def init_all_RL_problems(self, all_points, all_edge_index, all_obs_traj):
        self.RL_all_points = all_points
        self.RL_all_edge_index = all_edge_index
        self.RL_all_obs_traj = all_obs_traj

    def init_RL_problem(self, index, create_policy_func):
        self.RL_points = self.RL_all_points[index]
        self.RL_edge_index = self.RL_all_edge_index[index]
        self.RL_edge_reward = create_policy_func(self.RL_points, self.RL_edge_index)
        self.RL_current_time = 0
        self.RL_current_index = 0

    def reset(self):
        self.RL_current_time = 0
        self.RL_current_index = 0
        return self.RL_current_index

    def sample_random_action(self):
        policy = self.RL_edge_reward[self.RL_current_index, :]
        ######### Take one step based on the policy ########
        candidates = np.where(policy != -1)[0].tolist()
        # action_index = np.random.choice(candidates)
        # next_node_index = candidates[action_index]
        next_node_index = np.random.choice(candidates)
        # action = self.RL_points[next_node_index]
        return next_node_index

    def step(self, new_state_index):
        ### action is the transition vector , the inputs are index of points###

        '''
        Collision detection module
        '''
        # must specify either action or new_state

        state = self.RL_points[self.RL_current_index]
        new_state = self.RL_points[new_state_index]

        done = False
        no_collision = self._edge_fp(state, new_state, self.RL_current_time)
        if no_collision and self.in_goal_region(new_state):
            done = True

        if no_collision:
            ## dist(init, goal) - dist(cur, goal)
            reward = self.RL_edge_reward[0, 0] - self.RL_edge_reward[self.RL_current_index, self.RL_current_index]
        else:
            reward = -10

        info = no_collision

        d = np.linalg.norm(self.RL_points[new_state_index] - self.RL_points[self.RL_current_index])
        K = int(np.ceil(d / self.speed))

        if d == 0:
            K = 1

        self.RL_current_time += K
        self.RL_current_index = new_state_index

        return new_state_index, reward, done, info