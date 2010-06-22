#!/usr/bin/env python

import unittest, os
import os.path
from math import pi, sqrt
import tempfile

from anuga.config import g, epsilon
from anuga.config import netcdf_mode_r, netcdf_mode_w, netcdf_mode_a
from anuga.utilities.numerical_tools import mean
from anuga.geometry.polygon import is_inside_polygon
from anuga.coordinate_transforms.geo_reference import Geo_reference
from anuga.abstract_2d_finite_volumes.quantity import Quantity
from anuga.geospatial_data.geospatial_data import Geospatial_data
from anuga.abstract_2d_finite_volumes.mesh_factory import rectangular_cross

from anuga.utilities.system_tools import get_pathname_from_package
from swb_domain import *

import numpy as num

# Get gateway to C implementation of flux function for direct testing
from shallow_water_ext import flux_function_central as flux_function




class Test_swb_distribute(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass




    def test_first_order_extrapolator_const_z(self):
        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [2.0, 0.0]
        d = [0.0, 4.0]
        e = [2.0, 2.0]
        f = [4.0, 0.0]

        points = [a, b, c, d, e, f]
        #             bac,     bce,     ecf,     dbe
        vertices = [[1,0,2], [1,2,4], [4,2,5], [3,1,4]]

        domain = Domain(points, vertices)
        val0 = 2. + 2.0/3
        val1 = 4. + 4.0/3
        val2 = 8. + 2.0/3
        val3 = 2. + 8.0/3

        zl = zr = -3.75    # Assume constant bed (must be less than stage)
        domain.set_quantity('elevation', zl*num.ones((4, 3), num.int)) #array default#
        domain.set_quantity('stage', [[val0, val0-1, val0-2],
                                      [val1, val1+1, val1],
                                      [val2, val2-2, val2],
                                      [val3-0.5, val3, val3]])

        domain._order_ = 1
        domain.distribute_to_vertices_and_edges()

        #Check that centroid values were distributed to vertices
        C = domain.quantities['stage'].centroid_values
        for i in range(3):
            assert num.allclose(domain.quantities['stage'].vertex_values[:,i],
                                C)




    def test_first_order_limiter_variable_z(self):
        '''Check that first order limiter follows bed_slope'''

        from anuga.config import epsilon

        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [2.0,0.0]
        d = [0.0, 4.0]
        e = [2.0, 2.0]
        f = [4.0,0.0]

        points = [a, b, c, d, e, f]
        #bac, bce, ecf, dbe
        vertices = [ [1,0,2], [1,2,4], [4,2,5], [3,1,4]]

        domain = Domain(points, vertices)
        val0 = 2.+2.0/3
        val1 = 4.+4.0/3
        val2 = 8.+2.0/3
        val3 = 2.+8.0/3

        domain.set_quantity('elevation', [[0,0,0], [6,0,0],
                                          [6,6,6], [6,6,6]])
        domain.set_quantity('stage', [[val0, val0, val0],
                                      [val1, val1, val1],
                                      [val2, val2, val2],
                                      [val3, val3, val3]])

        E = domain.quantities['elevation'].vertex_values
        L = domain.quantities['stage'].vertex_values


        #Check that some stages are not above elevation (within eps)
        #- so that the limiter has something to work with
        assert not num.alltrue(num.alltrue(num.greater_equal(L,E-epsilon)))

        domain._order_ = 1
        domain.distribute_to_vertices_and_edges()

        #Check that all stages are above elevation (within eps)
        assert num.alltrue(num.alltrue(num.greater_equal(L,E-epsilon)))





    def test_distribute_basic(self):
        #Using test data generated by abstract_2d_finite_volumes-2
        #Assuming no friction and flat bed (0.0)

        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [2.0, 0.0]
        d = [0.0, 4.0]
        e = [2.0, 2.0]
        f = [4.0, 0.0]

        points = [a, b, c, d, e, f]
        #             bac,     bce,     ecf,     dbe
        vertices = [[1,0,2], [1,2,4], [4,2,5], [3,1,4]]

        domain = Domain(points, vertices)

        val0 = 2.
        val1 = 4.
        val2 = 8.
        val3 = 2.

        domain.set_quantity('stage', [val0, val1, val2, val3],
                            location='centroids')
        L = domain.quantities['stage'].vertex_values

        # First order
        domain.set_default_order(1)
        domain.distribute_to_vertices_and_edges()
        
        assert num.allclose(L[1], val1)

        # Second order
        domain.set_default_order(2)
        domain.distribute_to_vertices_and_edges()

        assert num.allclose(L[1], [0.0,   6.0,  6.0], atol=2.0e-3 )

        assert num.allclose(val1, num.sum(L[1])/3)

    def test_distribute_away_from_bed(self):
        #Using test data generated by abstract_2d_finite_volumes-2
        #Assuming no friction and flat bed (0.0)

        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [2.0, 0.0]
        d = [0.0, 4.0]
        e = [2.0, 2.0]
        f = [4.0, 0.0]

        points = [a, b, c, d, e, f]
        #             bac,     bce,     ecf,     dbe
        vertices = [[1,0,2], [1,2,4], [4,2,5], [3,1,4]]

        domain = Domain(points, vertices)
        L = domain.quantities['stage'].vertex_values

        def stage(x, y):
            return x**2

        domain.set_quantity('stage', stage, location='centroids')
        domain.set_quantity('elevation',-3.0)

        domain.quantities['stage'].compute_gradients()

        a, b = domain.quantities['stage'].get_gradients()

        assert num.allclose(a[1], 3.33333334)
        assert num.allclose(b[1], 0.0)

        domain.set_default_order(1)
        domain.distribute_to_vertices_and_edges()

        f1 = stage(4.0/3.0, 4.0/3.0)
        assert num.allclose(L[1], f1)

        domain.set_default_order(2)
        domain.distribute_to_vertices_and_edges()


        fv0 = f1 - a[1]*4.0/3.0 + b[1]*2.0/3.0
        fv1 = f1 + a[1]*2.0/3.0 - b[1]*4.0/3.0
        fv2 = f1 + a[1]*2.0/3.0 + b[1]*2.0/3.0

        assert num.allclose(L[1], [fv0,fv1,fv2])

        assert num.allclose(f1, num.sum(L[1])/3)

    def test_distribute_away_from_bed1(self):
        #Using test data generated by abstract_2d_finite_volumes-2
        #Assuming no friction and flat bed (0.0)

        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [2.0, 0.0]
        d = [0.0, 4.0]
        e = [2.0, 2.0]
        f = [4.0, 0.0]

        points = [a, b, c, d, e, f]
        #             bac,     bce,     ecf,     dbe
        vertices = [[1,0,2], [1,2,4], [4,2,5], [3,1,4]]

        domain = Domain(points, vertices)
        L = domain.quantities['stage'].vertex_values

        def stage(x, y):
            return x**4 + y**2

        domain.set_quantity('stage', stage, location='centroids')
        domain.set_quantity('elevation', -10.0)

        domain.quantities['stage'].compute_gradients()
        a, b = domain.quantities['stage'].get_gradients()
        assert num.allclose(a[1], 25.18518519)
        assert num.allclose(b[1], 3.33333333)

        domain.set_default_order(1)
        domain.distribute_to_vertices_and_edges()

        f1 = stage(4.0/3.0, 4.0/3.0)
        assert num.allclose(L[1], f1)

        domain.set_default_order(2)
        domain.distribute_to_vertices_and_edges()


        fv0 = f1 - a[1]*4.0/3.0 + b[1]*2.0/3.0
        fv1 = f1 + a[1]*2.0/3.0 - b[1]*4.0/3.0
        fv2 = f1 + a[1]*2.0/3.0 + b[1]*2.0/3.0

        
        assert num.allclose(L[1], [ fv0, fv1, fv2]) or \
               num.allclose(L[1], [ -9.23392657,  10.51787718,  13.5308642 ]) 


    def test_distribute_near_bed(self):
        a = [0.0, 0.0]
        b = [0.0, 2.0]
        c = [1.0, 1.0]
        d = [2.0, 0.0]
        e = [2.0, 2.0]
    

        points = [a, b, c, d, e]

        vertices = [[0,3,2], [0,2,1], [2,3,4], [1,2,4]]

        domain = Domain(points, vertices)

        # Set up for a gradient of (10,0) at mid triangle (bce)
        def slope(x, y):
            return 10*x

        h = 0.1
        def stage(x, y):
            return slope(x, y) + h

        domain.set_quantity('elevation', slope, location='centroids')
        domain.set_quantity('stage', stage, location='centroids')



        E = domain.quantities['elevation']
        L = domain.quantities['stage']
        Z = domain.quantities['elevation']

        E_V = E.vertex_values
        L_V = L.vertex_values

        E_E = E.edge_values
        L_E = L.edge_values        
        E_C = E.centroid_values
        L_C = L.centroid_values


        domain.set_default_order(1)
        domain.distribute_to_vertices_and_edges()

        assert num.allclose(L_V,[[ 10.1,         10.1,         10.1       ],
                                 [  3.43333333,   3.43333333,   3.43333333],
                                 [ 16.76666667,  16.76666667,  16.76666667],
                                 [ 10.1,         10.1,         10.1       ]])

        assert num.allclose(E_V,[[ 10.,          10.,          10.,        ],
                                 [  3.33333333,   3.33333333,   3.33333333],
                                 [ 16.66666667,  16.66666667,  16.66666667],
                                 [ 10.,          10.,          10.        ]])

        domain.set_default_order(2)

        # Setup the elevation to be pw linear (actually linear)
        Z.extrapolate_second_order_and_limit_by_edge()


        domain.distribute_to_vertices_and_edges()



        assert num.allclose(L_V,[[  0.1,  20.1,  10.1],
                                 [  0.1,  10.1,   0.1],
                                 [ 10.1,  20.1,  20.1],
                                 [  0.1,  10.1,  20.1]]) or \
               num.allclose(L_V,[[  0.1,         20.1,         10.1,       ],
                                 [  3.43333333,   3.43333333,   3.43333333],
                                 [ 16.76666667,  16.76666667,  16.76666667],
                                 [  0.1,         10.1,         20.1       ]])
        

        assert num.allclose(E_V,[[  0.,  20.,  10.],
                                 [  0.,  10.,   0.],
                                 [ 10.,  20.,  20.],
                                 [  0.,  10.,  20.]]) or \
               num.allclose(E_V,[[  0.,          20.,          10.,        ],
                                 [  3.33333333,   3.33333333,   3.33333333],
                                 [ 16.66666667,  16.66666667,  16.66666667],
                                 [  0.,          10.,          20.        ]])

                                 

        

    def test_second_order_distribute_real_data(self):
        #Using test data generated by abstract_2d_finite_volumes-2
        #Assuming no friction and flat bed (0.0)

        a = [0.0, 0.0]
        b = [0.0, 1.0/5]
        c = [0.0, 2.0/5]
        d = [1.0/5, 0.0]
        e = [1.0/5, 1.0/5]
        f = [1.0/5, 2.0/5]
        g = [2.0/5, 2.0/5]

        points = [a, b, c, d, e, f, g]
        #             bae,     efb,     cbf,     feg
        vertices = [[1,0,4], [4,5,1], [2,1,5], [5,4,6]]

        domain = Domain(points, vertices)

        def slope(x, y):
            return -x/3

        domain.set_quantity('elevation', slope)
        domain.set_quantity('stage',
                            [0.01298164, 0.00365611,
                             0.01440365, -0.0381856437096],
                            location='centroids')
        domain.set_quantity('xmomentum',
                            [0.00670439, 0.01263789,
                             0.00647805, 0.0178180740668],
                            location='centroids')
        domain.set_quantity('ymomentum',
                            [-7.23510980e-004, -6.30413883e-005,
                             6.30413883e-005, 0.000200907255866],
                            location='centroids')

        E = domain.quantities['elevation'].vertex_values
        L = domain.quantities['stage'].vertex_values
        X = domain.quantities['xmomentum'].vertex_values
        Y = domain.quantities['ymomentum'].vertex_values

        domain.set_default_order(2)

        domain.distribute_to_vertices_and_edges()


        assert num.allclose(L[1,:],
                            [-0.01434766, -0.01292565, 0.03824164], atol=1.0e-2)

        assert num.allclose(X[1,:],
                            [ 0.01702702, 0.01676034,  0.0057706 ], atol=1.0e-2)

        assert num.allclose(Y[1,:],
                            [-0.00041792,  0.00076771, -0.00039118], atol=1.0e-4)



#################################################################################

if __name__ == "__main__":
    suite = unittest.makeSuite(Test_swb_distribute, 'test')
    runner = unittest.TextTestRunner(verbosity=1)
    runner.run(suite)
